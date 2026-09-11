# SPDX-License-Identifier: GPL-3.0-or-later
"""Local recovery copies for explicitly approved temporary-layer removals."""

import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from qgis.core import (
    QgsApplication, QgsFeatureRequest, QgsLayerTreeGroup, QgsProject, QgsVectorFileWriter, QgsVectorLayer,
)


class RemovedLayerRecovery:
    def __init__(self, project_key, root=None):
        base = Path(root) if root else Path(QgsApplication.qgisSettingsDirPath()) / "qgis_ai_copilot" / "recovery"
        self.root = base / hashlib.sha256(project_key.encode()).hexdigest()[:24]
        self._held = {}
        self._active = True
        self.project = QgsProject.instance()
        self.project.cleared.connect(self._invalidate)

    def _invalidate(self):
        self._active = False
        self._held.clear()

    def close(self):
        self._invalidate()
        try:
            self.project.cleared.disconnect(self._invalidate)
        except (TypeError, RuntimeError):
            pass

    def rebind(self, project_key):
        destination = self.root.parent / hashlib.sha256(project_key.encode()).hexdigest()[:24]
        if destination == self.root:
            return
        if self.root.exists():
            if not destination.exists():
                self.root.rename(destination)
            else:
                entries = list(self.root.iterdir())
                if any((destination / entry.name).exists() for entry in entries):
                    raise OSError("A recovery entry already exists at the saved project destination.")
                moved = []
                try:
                    for entry in entries:
                        entry.rename(destination / entry.name)
                        moved.append(entry.name)
                except OSError:
                    for name in reversed(moved):
                        (destination / name).rename(self.root / name)
                    raise
        self.root = destination

    def _folder(self, recovery_id):
        if not isinstance(recovery_id, str) or not re.fullmatch(r"[0-9a-f]{32}", recovery_id):
            raise ValueError("Invalid recovery entry.")
        return self.root / recovery_id

    def _write(self, recovery_id, record):
        folder = self._folder(recovery_id)
        temporary = folder / "manifest.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(record, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, folder / "manifest.json")

    def _read(self, recovery_id):
        with (self._folder(recovery_id) / "manifest.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def backup(self, layer):
        if layer.providerType() != "memory" or layer.isEditable() or layer.subsetString() or layer.vectorJoins():
            raise ValueError("Only non-editing memory layers can be removed.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        recovery_id = uuid.uuid4().hex
        folder = self._folder(recovery_id)
        folder.mkdir(mode=0o700)
        node = self.project.layerTreeRoot().findLayer(layer.id())
        if node is None:
            raise ValueError("The layer is no longer in the project tree.")
        parent = node.parent()
        groups = []
        group = parent
        while group is not self.project.layerTreeRoot():
            groups.insert(0, {"name": group.name(), "index": group.parent().children().index(group)})
            group = group.parent()
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "recovered"
        fid_name = "_copilot_recovery_fid"
        while fid_name in layer.fields().names():
            fid_name = "_" + fid_name
        options.layerOptions = ["FID=" + fid_name]
        # A private directory is created before GDAL writes the data.
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, str(folder / "layer.gpkg"), self.project.transformContext(), options
        )
        if result[0] != QgsVectorFileWriter.NoError:
            raise OSError("Recovery copy failed; the layer was not removed.")
        saved = QgsVectorLayer(str(folder / "layer.gpkg"), "recovered", "ogr")
        if not saved.isValid() or saved.featureCount() != layer.featureCount():
            raise OSError("Recovery validation failed; the layer was not removed.")
        style_result = layer.saveNamedStyle(str(folder / "layer.qml"))
        if not style_result[-1]:
            raise OSError("Recovery style could not be saved; the layer was not removed.")
        for child in folder.iterdir():
            if child.is_file():
                os.chmod(child, 0o600)
        record = {
            "status": "removed", "layer_id": layer.id(), "name": layer.name(),
            "feature_count": layer.featureCount(), "opacity": layer.opacity(),
            "fields": layer.fields().names(),
            "visible": node.itemVisibilityChecked(), "expanded": node.isExpanded(),
            "groups": groups, "index": parent.children().index(node),
        }
        self._write(recovery_id, record)
        return recovery_id

    def retain(self, recovery_id, layer):
        self._held[recovery_id] = layer

    def available(self, recovery_id):
        if not self._active:
            return False
        try:
            record = self._read(recovery_id)
            return (
                record.get("status") in {"removed", "restoring"}
                and self.project.mapLayer(record["layer_id"]) is None
                and self.project.mapLayer(record.get("restoring_layer_id", "")) is None
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def status(self, recovery_id):
        try:
            record = self._read(recovery_id)
            if record.get("status") == "restoring" and self.project.mapLayer(record.get("restoring_layer_id", "")):
                return "restored"
            return record.get("status", "unavailable")
        except (OSError, ValueError, KeyError, TypeError):
            return "unavailable"

    def entries(self):
        if not self.root.exists():
            return []
        output = []
        for folder in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if self.available(folder.name):
                output.append((folder.name, self._read(folder.name)))
        return output

    def restore(self, recovery_id):
        if not self.available(recovery_id):
            raise ValueError("That layer has already been restored or belongs to another project.")
        record = self._read(recovery_id)
        layer = self._held.get(recovery_id)
        if layer is None:
            folder = self._folder(recovery_id)
            saved = QgsVectorLayer(str(folder / "layer.gpkg"), record["name"], "ogr")
            if not saved.isValid():
                raise ValueError("The recovery copy could not be opened.")
            request = QgsFeatureRequest()
            request.setSubsetOfAttributes(record.get("fields", saved.fields().names()), saved.fields())
            layer = saved.materialize(request)
            layer.setName(record["name"])
            layer.loadNamedStyle(str(folder / "layer.qml"))
            layer.setOpacity(record["opacity"])
        record["status"] = "restoring"
        record["restoring_layer_id"] = layer.id()
        self._write(recovery_id, record)
        root = self.project.layerTreeRoot()
        parent = root
        for entry in record["groups"]:
            name = entry["name"] if isinstance(entry, dict) else entry
            index = entry.get("index", -1) if isinstance(entry, dict) else -1
            children = parent.children()
            match = children[index] if 0 <= index < len(children) else None
            if not isinstance(match, QgsLayerTreeGroup) or match.name() != name:
                candidates = [child for child in children if isinstance(child, QgsLayerTreeGroup) and child.name() == name]
                match = candidates[0] if len(candidates) == 1 else None
            if match is None:
                parent = root
                break
            parent = match
        try:
            self.project.addMapLayer(layer, False)
            node = parent.insertLayer(min(record["index"], len(parent.children())), layer)
            node.setItemVisibilityChecked(record["visible"])
            node.setExpanded(record["expanded"])
            record["status"] = "restored"
            self._write(recovery_id, record)
        except Exception:
            if self.project.mapLayer(layer.id()) is not None:
                self._held[recovery_id] = self.project.takeMapLayer(layer)
            record["status"] = "removed"
            try:
                self._write(recovery_id, record)
            except OSError:
                pass
            raise
        self._held.pop(recovery_id, None)
        return layer
