# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated QGIS actions; no arbitrary Python, output paths, or source writes."""

import re
from copy import deepcopy
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsUnitTypes,
    QgsCoordinateReferenceSystem,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingAlgRunnerTask,
    QgsSymbol,
    QgsSingleSymbolRenderer,
)

from .agent_tools import ALGORITHMS, number, parse_arguments, validate_tool_arguments
from .storage import _redact_context_text
from .recovery import RemovedLayerRecovery
from .inspection import DATA_TOOLS, INSPECTION_TOOLS, READERS, data_scope, validate_fields

MAX_SOURCE_FEATURES = 250000
MAX_PROCESSING_SECONDS = 300


@dataclass
class ActionPlan:
    name: str
    args: dict
    mutating: bool
    description: str
    project: object
    layers: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    shares_data: bool = False
    data_scope: dict = field(default_factory=dict)


def layer_metadata(layer, fields=False):
    result = {
        "id": layer.id(),
        "name": _redact_context_text(layer.name())[:256],
        "crs": layer.crs().authid(),
        "type": "vector" if isinstance(layer, QgsVectorLayer) else "raster",
        "is_temporary_memory": isinstance(layer, QgsVectorLayer) and layer.providerType() == "memory",
    }
    if isinstance(layer, QgsVectorLayer):
        result.update(
            geometry=QgsWkbTypes.displayString(layer.wkbType()),
            feature_count=layer.featureCount(),
            selected_count=layer.selectedFeatureCount(),
            map_units=QgsUnitTypes.toString(layer.crs().mapUnits()),
        )
        if fields:
            result["fields"] = [
                {"name": _redact_context_text(f.name()), "type": f.typeName()}
                for f in list(layer.fields())[:80]
            ]
            result["fields_truncated"] = len(layer.fields()) > 80
    return result


class QgisToolExecutor(QObject):
    progress = pyqtSignal(float)

    def __init__(self, iface, parent=None, recovery=None):
        super().__init__(parent)
        self.iface = iface
        self._state = None
        self._serial = 0
        self.recovery = recovery or RemovedLayerRecovery(QgsProject.instance().fileName() or "unsaved")
        self._rollback = None
        self._layer_revisions = {}
        self._watched_layers = set()
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._processing_timeout)

    def _watch_layer(self, layer):
        layer_id = layer.id()
        if layer_id in self._watched_layers:
            return
        self._watched_layers.add(layer_id)
        self._layer_revisions.setdefault(layer_id, 0)
        signal = getattr(layer, "layerModified", layer.dataChanged)
        signal.connect(
            lambda layer_id=layer_id: self._layer_revisions.__setitem__(
                layer_id, self._layer_revisions.get(layer_id, 0) + 1
            )
        )

    def _layer(self, layer_id, geometry="vector"):
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None or not layer.isValid():
            raise ValueError(
                "Layer is missing or invalid. Inspect the current project and use its layer id."
            )
        if geometry != "any" and not isinstance(layer, QgsVectorLayer):
            raise ValueError("This operation requires a vector layer.")
        expected = {"point": QgsWkbTypes.PointGeometry, "polygon": QgsWkbTypes.PolygonGeometry}
        if geometry in expected and layer.geometryType() != expected[geometry]:
            raise ValueError(f"This input must contain {geometry} geometries.")
        return layer

    def _signature(self, layer):
        self._watch_layer(layer)
        return (
            layer,
            layer.crs().authid(),
            tuple(f.name() for f in layer.fields()) if isinstance(layer, QgsVectorLayer) else (),
            layer.featureCount() if isinstance(layer, QgsVectorLayer) else 0,
            self._layer_revisions.get(layer.id(), 0),
            layer.source(),
            layer.subsetString() if isinstance(layer, QgsVectorLayer) else "",
            layer.name(),
            layer.isEditable() if isinstance(layer, QgsVectorLayer) else False,
        )

    def prepare(self, name, args):
        validate_tool_arguments(name, args)
        args = deepcopy(args)
        project = QgsProject.instance()
        plan = ActionPlan(
            name,
            args,
            name in {"run_processing", "style_layer", "zoom_to_layer", "set_layer_visibility", "remove_temporary_layer"},
            name.replace("_", " ").capitalize(),
            project,
        )
        if name in INSPECTION_TOOLS:
            layer = self._layer(args["layer_id"])
            names = args.get("fields", [args["field_name"]] if "field_name" in args else [])
            validate_fields(layer, names)
            plan.layers[layer.id()] = self._signature(layer)
            plan.shares_data = name in DATA_TOOLS
            plan.data_scope = data_scope(name, args, layer)
            # Keep the approval tied to the same source/filter/revision, in memory only.
            plan.data_scope["layer_state"] = plan.layers[layer.id()][1:]
            scope = "geometry checks, bounds and small WKT" if name == "inspect_layer_geometry" else ", ".join(names)
            plan.description = f"Read layer: {_redact_context_text(layer.name())[:256]}\n{layer.featureCount()} features\n{scope}\nRead-only; no layer values or project settings will be changed."
            return plan
        if name in {"inspect_layer", "style_layer", "zoom_to_layer", "set_layer_visibility", "remove_temporary_layer"}:
            layer = self._layer(
                args["layer_id"], "vector" if name in {"inspect_layer", "style_layer"} else "any"
            )
            plan.layers[layer.id()] = self._signature(layer)
            plan.description = f"{name.replace('_', ' ').capitalize()}: {layer.name()}"
            if name == "remove_temporary_layer":
                if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "memory":
                    raise ValueError("Only temporary memory layers can be removed. Source files remain unchanged.")
                if layer.isEditable() or not 0 <= layer.featureCount() <= MAX_SOURCE_FEATURES:
                    raise ValueError("Finish editing or use a smaller memory layer before removal.")
                if layer.subsetString() or layer.vectorJoins():
                    raise ValueError("Remove filters/joins or export this memory layer before removing it, so its recovery copy is complete.")
                plan.description = (
                    f"Remove temporary layer: {_redact_context_text(layer.name())[:256]}\n"
                    f"{layer.featureCount():,} features; {layer.crs().authid()}\n"
                    "A private recovery copy will be saved first. Undo is available in Copilot. "
                    "No source file will be deleted."
                )
            if name == "style_layer":
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", args["color"]):
                    raise ValueError("Color must be a six-digit hex RGB color.")
                if layer.geometryType() not in {
                    QgsWkbTypes.PointGeometry,
                    QgsWkbTypes.LineGeometry,
                    QgsWkbTypes.PolygonGeometry,
                }:
                    raise ValueError("Layer geometry does not support a symbol renderer.")
                plan.description += f"\nUniform color {args['color']}, opacity {args['opacity']:.0%}. Replaces the current renderer; feature data is unchanged."
            if name == "set_layer_visibility":
                plan.description += (
                    "\n" + ("Show" if args["visible"] else "Hide") + " layer; nothing is deleted."
                )
        if name in {"describe_processing", "run_processing"}:
            algorithm = QgsApplication.processingRegistry().algorithmById(args["algorithm_id"])
            if algorithm is None:
                raise ValueError(
                    "This supported algorithm is not installed. Enable QGIS native Processing."
                )
        if name == "run_processing":
            spec = ALGORITHMS[args["algorithm_id"]]
            values = parse_arguments(args["parameters_json"])
            allowed = set(spec["layers"]) | set(spec["values"])
            if set(values) - allowed or (set(spec["layers"]) | set(spec["required"])) - set(values):
                raise ValueError(
                    "Invalid processing parameters. Use describe_processing; output paths and extra parameters are blocked."
                )
            label = args["result_name"].strip()
            if not label or len(label) > 100 or any(c in label for c in "/\\\n\r\x00"):
                raise ValueError("Choose a short result name, not a file path.")
            plan.parameters = {**spec["defaults"], **values, "OUTPUT": "memory:"}
            for key, geometry in spec["layers"].items():
                if not isinstance(values[key], str):
                    raise ValueError("Layer inputs must be layer ids.")
                layer = self._layer(values[key], geometry)
                if not 0 <= layer.featureCount() <= MAX_SOURCE_FEATURES:
                    raise ValueError(
                        "Input exceeds 250,000 features. Use a smaller layer for this Execute alpha."
                    )
                if not layer.crs().isValid():
                    raise ValueError("The input CRS is unknown. Resolve it before processing.")
                if layer.isEditable():
                    raise ValueError(
                        "Finish or discard the layer's edit session in QGIS before running this operation."
                    )
                plan.layers[layer.id()] = self._signature(layer)
            for key, rule in spec["values"].items():
                if key not in plan.parameters:
                    continue
                value = plan.parameters[key]
                if rule[0] in {"number", "int"}:
                    number(value, rule[1], rule[2], rule[0] == "int")
                elif rule[0] == "bool" and not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean.")
                elif rule[0] == "crs":
                    if (
                        not isinstance(value, str)
                        or not re.fullmatch(r"EPSG:\d{3,8}", value, re.I)
                        or not QgsCoordinateReferenceSystem(value).isValid()
                    ):
                        raise ValueError(
                            "TARGET_CRS must be a valid EPSG identifier, not a path or pipeline."
                        )
                elif rule[0] == "fields":
                    source = self._layer(values[rule[1]])
                    if (
                        not isinstance(value, list)
                        or len(value) > 20
                        or any(
                            not isinstance(f, str) or source.fields().indexFromName(f) < 0
                            for f in value
                        )
                    ):
                        raise ValueError("Dissolve fields must exist in the input layer.")
                elif rule[0] == "new_field":
                    if not isinstance(value, str) or not re.fullmatch(
                        r"[A-Za-z][A-Za-z0-9_]{0,39}", value
                    ):
                        raise ValueError("Output field must be a short identifier.")
                    if self._layer(values["POLYGONS"]).fields().indexFromName(value) >= 0:
                        raise ValueError(
                            "The output count field already exists; choose a new name."
                        )
            if (
                args["algorithm_id"] == "native:buffer"
                and self._layer(values["INPUT"]).crs().isGeographic()
            ):
                raise ValueError(
                    "Buffer uses input map units. Reproject the layer to an appropriate projected CRS first; degrees are not metres."
                )
            if (
                len(plan.layers) > 1
                and len({signature[1] for signature in plan.layers.values()}) > 1
            ):
                raise ValueError(
                    "Inputs use different CRS. Reproject them to the same CRS before this operation."
                )
            descriptions = [
                f"{key}: {self._layer(values[key]).name()} ({self._layer(values[key]).featureCount():,} features; {self._layer(values[key]).crs().authid()})"
                for key in spec["layers"]
            ]
            units = sorted(
                {
                    QgsUnitTypes.toString(self._layer(values[key]).crs().mapUnits())
                    for key in spec["layers"]
                }
            )
            descriptions.append("Input map units: " + ", ".join(units))
            descriptions += [
                f"{key}: {value}"
                for key, value in plan.parameters.items()
                if key not in spec["layers"] and key != "OUTPUT"
            ]
            plan.description = (
                f"Run {algorithm.displayName()}\n"
                + "\n".join(descriptions)
                + f"\nCreate temporary layer: {label}\nAll features are processed (not only selected features). Source layers are unchanged. Save the result manually in QGIS to keep it after closing."
            )
        return plan

    def _valid(self, plan):
        if plan.project is not QgsProject.instance():
            raise ValueError("Project changed.")
        for key, signature in plan.layers.items():
            current = QgsProject.instance().mapLayer(key)
            if (
                current is None
                or self._signature(current) != signature
                or (plan.name == "run_processing" and current.isEditable())
                or (plan.name == "remove_temporary_layer" and (
                    current.providerType() != "memory" or current.isEditable()
                    or current.subsetString() or current.vectorJoins()
                ))
            ):
                raise ValueError(
                    "An input layer changed while awaiting approval; inspect and propose the action again."
                )
            if plan.args.get("selected_only") and sorted(current.selectedFeatureIds()) != plan.data_scope["selected_ids"]:
                raise ValueError(
                    "The selection changed while awaiting approval; request permission for the new selection."
                )

    def execute(self, plan, done):
        if self._state is not None:
            raise ValueError("A QGIS task is already running.")
        self._rollback = None
        self._valid(plan)
        name, args = plan.name, plan.args
        project = QgsProject.instance()
        if name in INSPECTION_TOOLS:
            done(READERS[name](self._layer(args["layer_id"]), args))
            return
        if name == "inspect_project":
            layers = list(project.mapLayers().values())
            active = self.iface.activeLayer()
            done(
                {
                    "ok": True,
                    "layers": [layer_metadata(layer) for layer in layers[:80]],
                    "active_layer_id": active.id() if active else None,
                    "truncated": len(layers) > 80,
                }
            )
        elif name == "inspect_layer":
            done({"ok": True, "layer": layer_metadata(self._layer(args["layer_id"]), True)})
        elif name == "list_processing":
            done(
                {
                    "ok": True,
                    "algorithms": [
                        {
                            "id": key,
                            "name": QgsApplication.processingRegistry()
                            .algorithmById(key)
                            .displayName(),
                        }
                        for key in ALGORITHMS
                        if QgsApplication.processingRegistry().algorithmById(key)
                    ],
                }
            )
        elif name == "describe_processing":
            spec = deepcopy(ALGORITHMS[args["algorithm_id"]])
            done(
                {
                    "ok": True,
                    "algorithm_id": args["algorithm_id"],
                    **spec,
                    "output": "new temporary vector layer",
                    "distance_units": "INPUT map units; buffer requires projected CRS",
                }
            )
        elif name == "run_processing":
            self._processing(plan, done)
        elif name == "remove_temporary_layer":
            layer = self._layer(args["layer_id"])
            metadata = layer_metadata(layer)
            recovery_id = self.recovery.backup(layer)
            self._valid(plan)
            detached = project.takeMapLayer(layer)
            if detached is None:
                raise ValueError("The layer could not be removed.")
            self.recovery.retain(recovery_id, detached)
            self._rollback = lambda: self.recovery.restore(recovery_id)
            done({
                "ok": True, "operation": name, "layer": metadata, "removed": True,
                "recovery_id": recovery_id, "source_files_deleted": False,
            })
        else:
            layer = self._layer(args["layer_id"], "any")
            if name == "style_layer":
                renderer, opacity = layer.renderer().clone(), layer.opacity()
                def undo_style():
                    layer.setRenderer(renderer)
                    layer.setOpacity(opacity)
                    layer.triggerRepaint()
                self._rollback = undo_style
                symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                symbol.setColor(QColor(args["color"]))
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))
                layer.setOpacity(float(args["opacity"]))
                layer.triggerRepaint()
                project.setDirty(True)
            elif name == "zoom_to_layer":
                extent = self.iface.mapCanvas().extent()
                active = self.iface.activeLayer()
                def undo_view():
                    self.iface.setActiveLayer(active)
                    self.iface.mapCanvas().setExtent(extent)
                    self.iface.mapCanvas().refresh()
                self._rollback = undo_view
                self.iface.setActiveLayer(layer)
                if hasattr(self.iface, "zoomToActiveLayer"):
                    self.iface.zoomToActiveLayer()
                else:
                    self.iface.mapCanvas().setExtent(layer.extent())
                    self.iface.mapCanvas().refresh()
            elif name == "set_layer_visibility":
                node = project.layerTreeRoot().findLayer(layer.id())
                if node is None:
                    raise ValueError("Layer tree entry is unavailable.")
                visible = node.itemVisibilityChecked()
                self._rollback = lambda: node.setItemVisibilityChecked(visible)
                node.setItemVisibilityChecked(args["visible"])
                project.setDirty(True)
            done(
                {
                    "ok": True,
                    "operation": name,
                    "layer": layer_metadata(layer),
                    "source_features_modified": False,
                }
            )

    def rollback_last(self):
        rollback, self._rollback = self._rollback, None
        if rollback is not None:
            rollback()
            return True
        return False

    def _processing(self, plan, done):
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        context.setTransformContext(QgsProject.instance().transformContext())
        feedback = QgsProcessingFeedback()
        params = deepcopy(plan.parameters)
        try:
            for key in ALGORITHMS[plan.args["algorithm_id"]]["layers"]:
                clone = self._layer(params[key]).clone()
                context.temporaryLayerStore().addMapLayer(clone)
                params[key] = clone
            algorithm = (
                QgsApplication.processingRegistry()
                .algorithmById(plan.args["algorithm_id"])
                .create()
            )
            ok, _message = algorithm.checkParameterValues(params, context)
            if not ok:
                raise ValueError(
                    "QGIS rejected the parameters. Check layer geometry and algorithm requirements."
                )
            task = QgsProcessingAlgRunnerTask(algorithm, params, context, feedback)
        except Exception:
            context.temporaryLayerStore().removeAllMapLayers()
            raise
        state = {
            "task": task,
            "context": context,
            "feedback": feedback,
            "cancelled": False,
            "timed_out": False,
            "plan": plan,
        }
        self._state = state
        feedback.progressChanged.connect(self.progress)

        def clear_state(task_state):
            if self._state is task_state:
                self._state = None

        def complete(success, outputs):
            if self._state is state:
                if state["cancelled"]:
                    QTimer.singleShot(0, lambda: clear_state(state))
                else:
                    self._state = None
            self._watchdog.stop()
            result = {"ok": False, "error": "Processing failed. No result layer was added."}
            try:
                if state["cancelled"] or feedback.isCanceled() or not success:
                    return
                self._valid(plan)
                layer = context.getMapLayer(str(outputs.get("OUTPUT") or ""))
                if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                    raise ValueError("Processing did not produce a valid vector layer.")
                layer = context.takeResultLayer(layer.id())
                if layer is None:
                    raise ValueError("Result ownership could not be transferred.")
                layer.setName(plan.args["result_name"].strip())
                metadata = layer_metadata(layer)
                QgsProject.instance().addMapLayer(layer)
                output_id = layer.id()
                self._rollback = lambda: QgsProject.instance().removeMapLayer(output_id)
                result = {
                    "ok": True,
                    "algorithm": plan.args["algorithm_id"],
                    "layer": metadata,
                    "temporary": True,
                    "source_features_modified": False,
                }
            except Exception as exc:
                result = {"ok": False, "error": _redact_context_text(str(exc))[:500]}
            finally:
                context.temporaryLayerStore().removeAllMapLayers()
                if not state["cancelled"] or state["timed_out"]:
                    done(result)

        task.executed.connect(complete)
        QgsApplication.taskManager().addTask(task)
        if self._state is state:
            self._watchdog.start(MAX_PROCESSING_SECONDS * 1000)

    def _processing_timeout(self):
        state = self._state
        if state is None:
            return
        state["timed_out"] = True
        state["cancelled"] = True
        state["feedback"].cancel()
        state["task"].cancel()

    def cancel(self):
        state = self._state
        if state:
            self._watchdog.stop()
            state["cancelled"] = True
            state["feedback"].cancel()
            state["task"].cancel()
