# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Privacy-aware QGIS context snapshots and allow-listed read-only checks."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsMapLayerType,
    QgsProcessing,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeatureSourceDefinition,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)


CONTEXT_LABELS = {
    "project_overview": "Project overview",
    "layer_inventory": "All project layers",
    "active_layer": "Active layer",
    "fields": "Fields",
    "selection": "Selection",
    "canvas": "Map view",
}

BACKGROUND_R0_TOOLS = {
    "calculate_field_statistics_local",
    "check_geometry_health",
}

R0_TOOLS = (
    "get_project_summary",
    "list_layers",
    "describe_layer",
    "list_fields",
    "get_selection_summary",
    "get_canvas_summary",
    "calculate_field_statistics_local",
    "check_crs_consistency",
    "check_geometry_health",
    "explain_processing_error",
    "find_processing_algorithm",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _layer_kind(layer) -> str:
    if layer.type() == QgsMapLayerType.VectorLayer:
        return "vector"
    if layer.type() == QgsMapLayerType.RasterLayer:
        return "raster"
    return "other"


def _geometry_name(layer) -> str:
    if not isinstance(layer, QgsVectorLayer):
        return "n/a"
    try:
        return QgsWkbTypes.displayString(layer.wkbType())
    except Exception:
        return "unknown"


class ContextCollector:
    def __init__(self, iface) -> None:
        self.iface = iface

    @property
    def project(self) -> QgsProject:
        return QgsProject.instance()

    def project_display_name(self) -> str:
        project = self.project
        return project.baseName() or project.title() or "Untitled project"

    def project_overview(self) -> dict[str, Any]:
        project = self.project
        layers = list(project.mapLayers().values())
        return {
            "name": self.project_display_name(),
            "crs": project.crs().authid() or "Unknown",
            "layer_count": len(layers),
        }

    def layer_inventory(self) -> list[dict[str, Any]]:
        return [
            {
                "name": layer.name(),
                "type": _layer_kind(layer),
                "geometry": _geometry_name(layer),
            }
            for layer in self.project.mapLayers().values()
        ]

    def project_summary(self) -> dict[str, Any]:
        return {**self.project_overview(), "layers": self.layer_inventory()}

    def active_layer_summary(self) -> dict[str, Any] | None:
        layer = self.iface.activeLayer()
        if layer is None:
            return None
        result: dict[str, Any] = {
            "name": layer.name(),
            "type": _layer_kind(layer),
            "provider": layer.providerType(),
            "crs": layer.crs().authid() or "Unknown",
            "valid": bool(layer.isValid()),
        }
        if isinstance(layer, QgsVectorLayer):
            result.update(
                {
                    "geometry": _geometry_name(layer),
                    "feature_count": int(layer.featureCount()),
                }
            )
        return result

    def fields_summary(self) -> list[dict[str, str]]:
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return []
        return [
            {"name": field.name(), "type": field.typeName() or str(field.type())}
            for field in layer.fields()
        ]

    def selection_summary(self) -> dict[str, Any]:
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return {"available": False, "count": 0}
        return {
            "available": True,
            "layer": layer.name(),
            "count": int(layer.selectedFeatureCount()),
        }

    def canvas_summary(self) -> dict[str, Any]:
        canvas = self.iface.mapCanvas()
        settings = canvas.mapSettings()
        size = settings.outputSize()
        return {
            "destination_crs": settings.destinationCrs().authid() or "Unknown",
            "scale": round(float(canvas.scale()), 2),
            "rotation_degrees": round(float(canvas.rotation()), 2),
            "viewport_pixels": {"width": size.width(), "height": size.height()},
            "exact_coordinates_included": False,
        }

    def snapshot(self, attached_keys: set[str], local_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "schema": 1,
            "captured_at": _utc_now(),
            "qgis_version": Qgis.version(),
            "included_context": sorted(key for key in attached_keys if key != "local_results"),
            "privacy": {
                "raw_attributes": False,
                "geometries": False,
                "exact_paths": False,
                "screenshots": False,
                "exact_coordinates": False,
            },
        }
        if "project_overview" in attached_keys:
            snapshot["project_overview"] = self.project_overview()
        if "layer_inventory" in attached_keys:
            snapshot["layer_inventory"] = self.layer_inventory()
        if "active_layer" in attached_keys:
            snapshot["active_layer"] = self.active_layer_summary()
        if "fields" in attached_keys:
            snapshot["fields"] = self.fields_summary()
        if "selection" in attached_keys:
            snapshot["selection"] = self.selection_summary()
        if "canvas" in attached_keys:
            snapshot["map_view"] = self.canvas_summary()
        if local_results:
            snapshot["local_read_only_results"] = local_results
        return snapshot

    def run_tool(self, tool_id: str, **parameters: Any) -> dict[str, Any]:
        if tool_id not in R0_TOOLS:
            raise ValueError("Tool is not in the Alpha read-only allow-list.")
        if tool_id in BACKGROUND_R0_TOOLS:
            raise ValueError("This check must run as a background QGIS task.")
        methods = {
            "get_project_summary": self.project_summary,
            "list_layers": self._list_layers,
            "describe_layer": self.active_layer_summary,
            "list_fields": self.fields_summary,
            "get_selection_summary": self.selection_summary,
            "get_canvas_summary": self.canvas_summary,
            "check_crs_consistency": self._check_crs,
            "explain_processing_error": self._explain_processing_error,
            "find_processing_algorithm": self._find_processing_algorithm,
        }
        result = methods[tool_id](**parameters)
        return self._tool_envelope(tool_id, result)

    @staticmethod
    def _tool_envelope(tool_id: str, result: Any) -> dict[str, Any]:
        return {
            "tool": tool_id,
            "risk": "R0 read-only",
            "ran_at": _utc_now(),
            "result": result,
        }

    def prepare_background_tool(
        self, tool_id: str, **parameters: Any
    ) -> tuple[
        QgsProcessingAlgRunnerTask,
        QgsProcessingContext,
        QgsProcessingFeedback,
        dict[str, Any],
    ]:
        if tool_id not in BACKGROUND_R0_TOOLS:
            raise ValueError("This check does not require a background task.")
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise ValueError("A valid vector layer is required.")

        context = QgsProcessingContext()
        context.setProject(self.project)
        context.setInvalidGeometryCheck(Qgis.InvalidGeometryCheck.NoCheck)
        feedback = QgsProcessingFeedback()
        metadata: dict[str, Any] = {
            "layer": layer.name(),
            "feature_count": int(layer.featureCount()),
        }
        if tool_id == "calculate_field_statistics_local":
            field_name = str(parameters.get("field_name") or "")
            index = layer.fields().indexOf(field_name)
            if index < 0:
                raise ValueError("Choose a field from the active layer.")
            limit = 10_000
            algorithm_id = "native:basicstatisticsforfields"
            source = QgsProcessingFeatureSourceDefinition(layer.id(), featureLimit=limit)
            task_parameters = {
                "INPUT_LAYER": source,
                "FIELD_NAME": field_name,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                "OUTPUT_HTML_FILE": QgsProcessing.TEMPORARY_OUTPUT,
            }
            metadata.update(
                {
                    "field": field_name,
                    "field_is_numeric": bool(layer.fields().at(index).isNumeric()),
                    "sample_limit": limit,
                }
            )
        else:
            limit = 5_000
            algorithm_id = "native:checkvalidity"
            source = QgsProcessingFeatureSourceDefinition(layer.id(), featureLimit=limit)
            task_parameters = {
                "INPUT_LAYER": source,
                "METHOD": 2,
                "IGNORE_RING_SELF_INTERSECTION": False,
                "VALID_OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                "INVALID_OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                "ERROR_OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            }
            metadata["sample_limit"] = limit

        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if algorithm is None:
            raise ValueError(f"QGIS Processing algorithm is unavailable: {algorithm_id}")
        task = QgsProcessingAlgRunnerTask(algorithm, task_parameters, context, feedback)
        return task, context, feedback, metadata

    def finalize_background_tool(
        self,
        tool_id: str,
        successful: bool,
        outputs: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not successful:
            raise ValueError("The QGIS Processing check did not complete successfully.")

        if tool_id == "calculate_field_statistics_local":
            count = int(outputs.get("COUNT") or 0)
            result: dict[str, Any] = {
                "layer": metadata["layer"],
                "field": metadata["field"],
                "sample_limit": metadata["sample_limit"],
                "sampled_features": count,
                "non_null_count": int(outputs.get("FILLED") or 0),
                "null_count": int(outputs.get("EMPTY") or 0),
                "unique_count": int(outputs.get("UNIQUE") or 0),
                "raw_values_included": False,
            }
            if metadata.get("field_is_numeric") and count:
                numeric_summary: dict[str, float] = {}
                for source_key, target_key in (
                    ("MIN", "minimum"),
                    ("MAX", "maximum"),
                    ("MEAN", "mean"),
                ):
                    try:
                        numeric_summary[target_key] = float(outputs[source_key])
                    except (KeyError, TypeError, ValueError):
                        pass
                numeric_summary["numeric_count"] = int(outputs.get("FILLED") or 0)
                result["numeric_summary"] = numeric_summary
        elif tool_id == "check_geometry_health":
            valid = int(outputs.get("VALID_COUNT") or 0)
            invalid = int(outputs.get("INVALID_COUNT") or 0)
            result = {
                "layer": metadata["layer"],
                "feature_count": metadata["feature_count"],
                "checked": valid + invalid,
                "sample_limit": metadata["sample_limit"],
                "complete": metadata["feature_count"] <= valid + invalid,
                "valid_geometries": valid,
                "invalid_geometries": invalid,
                "validation_errors": int(outputs.get("ERROR_COUNT") or 0),
                "source_modified": False,
            }
        else:
            raise ValueError("Unknown background check result.")
        return self._tool_envelope(tool_id, result)

    def _list_layers(self) -> list[dict[str, Any]]:
        return self.layer_inventory()

    def _check_crs(self) -> dict[str, Any]:
        layer = self.iface.activeLayer()
        if layer is None:
            raise ValueError("An active layer is required.")
        project_crs = self.project.crs().authid() or "Unknown"
        layer_crs = layer.crs().authid() or "Unknown"
        return {
            "project_crs": project_crs,
            "active_layer": layer.name(),
            "layer_crs": layer_crs,
            "matches_project": project_crs == layer_crs,
        }

    @staticmethod
    def _explain_processing_error(error_text: str = "") -> dict[str, Any]:
        text = " ".join(error_text.split())[:1000]
        lower = text.lower()
        if "crs" in lower or "coordinate" in lower:
            category = "CRS or coordinate-system mismatch"
        elif "geometry" in lower or "geos" in lower:
            category = "Geometry validity or type mismatch"
        elif "field" in lower or "attribute" in lower:
            category = "Field or attribute mismatch"
        elif "permission" in lower or "read-only" in lower:
            category = "File access or output permission"
        else:
            category = "Unclassified processing error"
        guidance = {
            "CRS or coordinate-system mismatch": [
                "Compare the project and input layer CRS.",
                "Confirm the algorithm expects projected or geographic units.",
            ],
            "Geometry validity or type mismatch": [
                "Check the input geometry type and multipart requirements.",
                "Run the local geometry health check before processing.",
            ],
            "Field or attribute mismatch": [
                "Confirm the field still exists and has the expected type.",
                "Check for renamed fields or unsupported null values.",
            ],
            "File access or output permission": [
                "Choose a writable output destination.",
                "Confirm the target dataset is not locked by another process.",
            ],
            "Unclassified processing error": [
                "Confirm required inputs and parameters in the Processing log.",
                "Re-run with a small local sample to isolate the failing input.",
            ],
        }
        return {
            "category": category,
            "checks": guidance[category],
            "original_error_included": False,
            "source_modified": False,
        }

    @staticmethod
    def _find_processing_algorithm(query: str = "") -> list[dict[str, str]]:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("Enter an algorithm name or keyword.")
        matches: list[dict[str, str]] = []
        for algorithm in QgsApplication.processingRegistry().algorithms():
            algorithm_id = algorithm.id()
            label = algorithm.displayName()
            if needle in algorithm_id.lower() or needle in label.lower():
                matches.append({"id": algorithm_id, "name": label})
            if len(matches) >= 12:
                break
        return matches


class ContextMonitor(QObject):
    staleChanged = pyqtSignal(bool, str)
    projectIdentityChanged = pyqtSignal(str, str, str)

    def __init__(self, iface, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.iface = iface
        self.project = QgsProject.instance()
        self.canvas = iface.mapCanvas()
        self._unsaved_id = f"unsaved-{uuid.uuid4().hex}"
        self._project_id = self.project_identity()
        self._selection_layer = None
        self._stale = False
        self._connect()

    def project_identity(self) -> str:
        path = self.project.fileName()
        if path:
            normalized = os.path.realpath(path).encode("utf-8")
            return "project-" + hashlib.sha256(normalized).hexdigest()[:24]
        return self._unsaved_id

    @property
    def current_project_id(self) -> str:
        return self._project_id

    def _connect(self) -> None:
        self.project.layersAdded.connect(self._project_content_changed)
        self.project.layersRemoved.connect(self._project_content_changed)
        self.project.crsChanged.connect(self._mark_project_stale)
        self.project.readProject.connect(self._project_changed)
        self.project.writeProject.connect(self._project_changed)
        self.project.cleared.connect(self._project_changed)
        self.canvas.extentsChanged.connect(self._mark_canvas_stale)
        self.canvas.destinationCrsChanged.connect(self._mark_canvas_stale)
        self.iface.currentLayerChanged.connect(self._active_layer_changed)
        self._active_layer_changed(self.iface.activeLayer())

    def _disconnect_selection(self) -> None:
        if isinstance(self._selection_layer, QgsVectorLayer):
            try:
                self._selection_layer.selectionChanged.disconnect(self._selection_changed)
            except (TypeError, RuntimeError):
                pass
        self._selection_layer = None

    def _active_layer_changed(self, layer) -> None:
        self._disconnect_selection()
        if isinstance(layer, QgsVectorLayer):
            self._selection_layer = layer
            layer.selectionChanged.connect(self._selection_changed)
        self.mark_stale("Active layer changed")

    def _selection_changed(self, *args) -> None:
        self.mark_stale("Selection changed")

    def _mark_canvas_stale(self, *args) -> None:
        self.mark_stale("Map view changed")

    def _mark_project_stale(self, *args) -> None:
        self.mark_stale("Project CRS changed")

    def _project_content_changed(self, *args) -> None:
        self.mark_stale("Project layers changed")

    def _project_changed(self, *args) -> None:
        previous = self._project_id
        current = self.project_identity()
        self._project_id = current
        self._active_layer_changed(self.iface.activeLayer())
        if current != previous:
            display = self.project.baseName() or self.project.title() or "Untitled project"
            self.projectIdentityChanged.emit(previous, current, display)
        self.mark_stale("Project changed")

    def mark_stale(self, reason: str) -> None:
        self._stale = True
        self.staleChanged.emit(True, reason)

    def mark_current(self) -> None:
        self._stale = False
        self.staleChanged.emit(False, "Context current")

    def close(self) -> None:
        self._disconnect_selection()
        for signal, slot in (
            (self.project.layersAdded, self._project_content_changed),
            (self.project.layersRemoved, self._project_content_changed),
            (self.project.crsChanged, self._mark_project_stale),
            (self.project.readProject, self._project_changed),
            (self.project.writeProject, self._project_changed),
            (self.project.cleared, self._project_changed),
            (self.canvas.extentsChanged, self._mark_canvas_stale),
            (self.canvas.destinationCrsChanged, self._mark_canvas_stale),
            (self.iface.currentLayerChanged, self._active_layer_changed),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
