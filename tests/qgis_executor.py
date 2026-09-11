"""Actual native QGIS mutations on synthetic layers, never the user's project."""

import importlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.core import QgsApplication, QgsProject, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsVectorLayer
from qgis.analysis import QgsNativeAlgorithms

from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface


class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        if not QgsApplication.processingRegistry().algorithmById("native:buffer"):
            QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.project, self.layer = synthetic_project()
        self.iface = FakeIface()
        self.iface.set_active_layer(self.layer)
        try:
            module = importlib.import_module("qgis_ai_copilot.executor")
        except ImportError:
            self.fail("Missing real QGIS tool executor")
        self.executor = module.QgisToolExecutor(self.iface)

    def tearDown(self):
        if hasattr(self, "executor"):
            self.executor.cancel()
        self.iface.window.close()
        self.project.clear()

    def run_plan(self, plan):
        loop = QEventLoop()
        results = []
        self.executor.execute(plan, lambda value: (results.append(value), loop.quit()))
        if not results:
            QTimer.singleShot(10000, loop.quit)
            loop.exec_()
        self.assertTrue(results, "Execution did not finish")
        return results[0]

    def test_inspection_uses_layer_ids_not_private_sources(self):
        plan = self.executor.prepare("inspect_project", {})
        self.assertFalse(plan.mutating)
        result = self.run_plan(plan)
        self.assertTrue(result["ok"])
        self.assertIn(self.layer.id(), str(result))
        self.assertNotIn("Polygon?", str(result))

    def test_remove_temporary_layer_preserves_data_for_undo(self):
        from qgis_ai_copilot.agent_tools import tool_definitions
        self.assertIn("remove_temporary_layer", [tool["name"] for tool in tool_definitions()])
        original_id = self.layer.id()
        original_values = [f.attributes() for f in self.layer.getFeatures()]
        original_geometries = [f.geometry().asWkt() for f in self.layer.getFeatures()]
        self.layer.setOpacity(0.45)
        self.project.layerTreeRoot().findLayer(original_id).setItemVisibilityChecked(False)
        plan = self.executor.prepare("remove_temporary_layer", {"layer_id": original_id})
        self.assertTrue(plan.mutating)
        self.assertIsNotNone(self.project.mapLayer(original_id))
        result = self.run_plan(plan)
        self.assertTrue(result["ok"])
        self.assertIsNone(self.project.mapLayer(original_id))
        self.assertEqual(len(self.project.mapLayers()), 1)
        recovered = self.executor.recovery.restore(result["recovery_id"])
        self.assertEqual(recovered.providerType(), "memory")
        self.assertEqual([f.attributes() for f in recovered.getFeatures()], original_values)
        self.assertEqual([f.geometry().asWkt() for f in recovered.getFeatures()], original_geometries)
        self.assertAlmostEqual(recovered.opacity(), 0.45)
        self.assertFalse(self.project.layerTreeRoot().findLayer(recovered.id()).itemVisibilityChecked())
        with self.assertRaises(ValueError):
            self.executor.recovery.restore(result["recovery_id"])

    def test_memory_removal_is_blocked_if_backup_fails(self):
        from qgis_ai_copilot.agent_tools import tool_definitions
        self.assertIn("remove_temporary_layer", [tool["name"] for tool in tool_definitions()])
        plan = self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()})
        with patch.object(self.executor.recovery, "backup", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_plan(plan)
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_disk_layer_is_not_removable_even_with_temporary_name(self):
        from qgis_ai_copilot.recovery import RemovedLayerRecovery
        recovery = RemovedLayerRecovery("fixture", root=self.temp.name)
        backup = recovery.backup(self.layer)
        disk = QgsVectorLayer(str(recovery._folder(backup) / "layer.gpkg"), "Temporary Intersection", "ogr")
        self.assertTrue(disk.isValid())
        self.project.addMapLayer(disk)
        with self.assertRaises(ValueError):
            self.executor.prepare("remove_temporary_layer", {"layer_id": disk.id()})
        self.assertIsNotNone(self.project.mapLayer(disk.id()))

    def test_disk_recovery_survives_a_new_recovery_controller(self):
        plan = self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()})
        result = self.run_plan(plan)
        from qgis_ai_copilot.recovery import RemovedLayerRecovery
        second = RemovedLayerRecovery(QgsProject.instance().fileName() or "unsaved")
        layer = second.restore(result["recovery_id"])
        self.assertEqual(layer.featureCount(), 2)
        self.assertEqual(layer.fields().names(), ["id", "name"])
        self.assertEqual(layer.crs().authid(), "EPSG:3857")
        self.assertEqual(sorted(f["name"] for f in layer.getFeatures()), ["Example 1", "Example 2"])

    def test_failed_restore_can_be_retried(self):
        plan = self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()})
        result = self.run_plan(plan)
        key = result["recovery_id"]
        with patch.object(self.project, "addMapLayer", side_effect=ValueError("failed to add")):
            with self.assertRaises(ValueError):
                self.executor.recovery.restore(key)
        self.assertTrue(self.executor.recovery.available(key))
        restored = self.executor.recovery.restore(key)
        self.assertEqual(restored.featureCount(), 2)

    def test_recovery_rebind_keeps_undo_after_first_project_save(self):
        result = self.run_plan(self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()}))
        self.assertTrue(hasattr(self.executor.recovery, "rebind"))
        self.executor.recovery.rebind("saved-project-fixture")
        from qgis_ai_copilot.recovery import RemovedLayerRecovery
        controller = RemovedLayerRecovery("saved-project-fixture")
        restored = controller.restore(result["recovery_id"])
        self.assertEqual(restored.featureCount(), 2)

    def test_restore_group_cannot_be_confused_with_a_same_named_layer(self):
        root = self.project.layerTreeRoot()
        other = next(layer for layer in self.project.mapLayers().values() if layer is not self.layer)
        other.setName("Bucket")
        group = root.addGroup("Bucket")
        node = root.findLayer(self.layer.id())
        group.addChildNode(node.clone())
        root.removeChildNode(node)
        result = self.run_plan(self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()}))
        restored = self.executor.recovery.restore(result["recovery_id"])
        self.assertIs(root.findLayer(restored.id()).parent(), group)

    def test_pending_removal_invalidates_when_layer_changes(self):
        from qgis_ai_copilot.agent_tools import tool_definitions
        self.assertIn("remove_temporary_layer", [tool["name"] for tool in tool_definitions()])
        plan = self.executor.prepare("remove_temporary_layer", {"layer_id": self.layer.id()})
        self.layer.startEditing()
        with self.assertRaises(ValueError):
            self.run_plan(plan)
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_invalid_new_action_cannot_roll_back_an_earlier_success(self):
        first = self.executor.prepare("style_layer", {
            "layer_id": self.layer.id(), "color": "#123456", "opacity": 0.3,
        })
        self.run_plan(first)
        second = self.executor.prepare("style_layer", {
            "layer_id": self.layer.id(), "color": "#654321", "opacity": 0.7,
        })
        self.layer.setName("Changed while awaiting approval")
        with self.assertRaises(ValueError):
            self.run_plan(second)
        self.assertFalse(self.executor.rollback_last())
        self.assertAlmostEqual(self.layer.opacity(), 0.3)

    def test_buffer_creates_memory_layer_and_leaves_source_untouched(self):
        plan = self.executor.prepare(
            "run_processing",
            {
                "algorithm_id": "native:buffer",
                "parameters_json": '{"INPUT":"' + self.layer.id() + '","DISTANCE":5}',
                "result_name": "Test buffer",
            },
        )
        self.assertTrue(plan.mutating)
        self.assertEqual(len(self.project.mapLayers()), 2)
        result = self.run_plan(plan)
        self.assertTrue(result["ok"], result)
        output = self.project.mapLayer(result["layer"]["id"])
        self.assertEqual(output.providerType(), "memory")
        self.assertEqual(output.featureCount(), self.layer.featureCount())
        self.assertGreater(output.extent().width(), self.layer.extent().width())
        self.assertEqual(self.layer.extent().width(), 30)

    def test_unknown_algorithms_paths_and_parameters_rejected(self):
        for args in [
            {
                "algorithm_id": "native:buffer",
                "parameters_json": '{"INPUT":"/tmp/private.gpkg","DISTANCE":5}',
                "result_name": "x",
            },
            {
                "algorithm_id": "native:buffer",
                "parameters_json": '{"INPUT":"'
                + self.layer.id()
                + '","DISTANCE":5,"OUTPUT":"/tmp/overwrite.gpkg"}',
                "result_name": "x",
            },
            {"algorithm_id": "script:python", "parameters_json": "{}", "result_name": "x"},
            {
                "algorithm_id": "native:buffer",
                "parameters_json": '{"INPUT":"' + self.layer.id() + '","DISTANCE":NaN}',
                "result_name": "x",
            },
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.executor.prepare("run_processing", args)
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_geographic_buffer_requires_reprojection(self):
        self.layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        with self.assertRaises(ValueError):
            self.executor.prepare(
                "run_processing",
                {
                    "algorithm_id": "native:buffer",
                    "parameters_json": '{"INPUT":"' + self.layer.id() + '","DISTANCE":500}',
                    "result_name": "bad",
                },
            )

    def test_reprojection_and_styling_are_real(self):
        plan = self.executor.prepare(
            "run_processing",
            {
                "algorithm_id": "native:reprojectlayer",
                "parameters_json": '{"INPUT":"' + self.layer.id() + '","TARGET_CRS":"EPSG:25832"}',
                "result_name": "Projected",
            },
        )
        result = self.run_plan(plan)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.project.mapLayer(result["layer"]["id"]).crs().authid(), "EPSG:25832")
        style = self.executor.prepare(
            "style_layer", {"layer_id": self.layer.id(), "color": "#1267bb", "opacity": 0.6}
        )
        self.assertTrue(style.mutating)
        self.assertTrue(self.run_plan(style)["ok"])
        self.assertAlmostEqual(self.layer.opacity(), 0.6)
        self.assertEqual(self.layer.renderer().symbol().color().name(), "#1267bb")

    def test_cancelled_task_does_not_publish_a_layer(self):
        plan = self.executor.prepare(
            "run_processing",
            {
                "algorithm_id": "native:buffer",
                "parameters_json": '{"INPUT":"' + self.layer.id() + '","DISTANCE":5}',
                "result_name": "Cancel",
            },
        )
        self.executor.execute(plan, lambda _result: None)
        self.executor.cancel()
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec_()
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_plan_invalidates_when_input_changes_before_approval(self):
        plan = self.executor.prepare(
            "style_layer", {"layer_id": self.layer.id(), "color": "#ff0000", "opacity": 0.5}
        )
        self.project.removeMapLayer(self.layer.id())
        with self.assertRaises(ValueError):
            self.executor.execute(plan, lambda value: None)

    def processing(self, algorithm, values, label="Result"):
        return self.executor.prepare("run_processing", {"algorithm_id": "native:" + algorithm, "parameters_json": json.dumps(values), "result_name": label})

    def test_cancel_retains_cleanup_state_until_terminal_callback(self):
        plan = self.processing("buffer", {"INPUT": self.layer.id(), "DISTANCE": 5})
        called = []
        self.executor.execute(plan, called.append)
        state = self.executor._state
        self.executor.cancel()
        self.assertIs(self.executor._state, state)
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec_()
        self.assertIsNone(self.executor._state)
        self.assertEqual(state["context"].temporaryLayerStore().count(), 0)
        self.assertEqual(called, [])
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_committed_attribute_edit_invalidates_pending_plan(self):
        plan = self.processing("buffer", {"INPUT": self.layer.id(), "DISTANCE": 5})
        feature = next(self.layer.getFeatures())
        self.layer.startEditing()
        self.layer.changeAttributeValue(feature.id(), 1, "Changed after approval preview")
        self.layer.commitChanges()
        with self.assertRaises(ValueError):
            self.executor.execute(plan, lambda value: None)

    def test_output_metadata_failure_does_not_add_unreported_layer(self):
        plan = self.processing("buffer", {"INPUT": self.layer.id(), "DISTANCE": 5})
        with patch("qgis_ai_copilot.executor.layer_metadata", side_effect=ValueError("metadata failed")):
            result = self.run_plan(plan)
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_all_supported_algorithms_create_valid_memory_outputs(self):
        points = next(layer for layer in self.project.mapLayers().values() if layer is not self.layer)
        for wkt in ("POINT(1 1)", "POINT(2 2)", "POINT(25 5)"):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            points.dataProvider().addFeatures([feature])
        points.updateExtents()
        cases = [
            ("clip", {"INPUT": self.layer.id(), "OVERLAY": self.layer.id()}, 2),
            ("intersection", {"INPUT": self.layer.id(), "OVERLAY": self.layer.id()}, 2),
            ("dissolve", {"INPUT": self.layer.id()}, 1),
            ("fixgeometries", {"INPUT": self.layer.id()}, 2),
            ("centroids", {"INPUT": self.layer.id()}, 2),
            ("countpointsinpolygon", {"POLYGONS": self.layer.id(), "POINTS": points.id()}, 2),
        ]
        for algorithm, values, count in cases:
            with self.subTest(algorithm=algorithm):
                result = self.run_plan(self.processing(algorithm, values))
                self.assertTrue(result["ok"], result)
                output = self.project.mapLayer(result["layer"]["id"])
                self.assertEqual(output.providerType(), "memory")
                self.assertEqual(output.featureCount(), count)
                if algorithm == "countpointsinpolygon":
                    self.assertEqual(sorted(f["NUMPOINTS"] for f in output.getFeatures()), [1, 2])

    def test_wrong_geometries_fields_and_crs_are_rejected(self):
        point = next(layer for layer in self.project.mapLayers().values() if layer is not self.layer)
        cases = [
            ("clip", {"INPUT": self.layer.id(), "OVERLAY": point.id()}),
            ("countpointsinpolygon", {"POLYGONS": point.id(), "POINTS": point.id()}),
            ("countpointsinpolygon", {"POLYGONS": self.layer.id(), "POINTS": point.id(), "FIELD": "name"}),
            ("dissolve", {"INPUT": self.layer.id(), "FIELD": ["missing"]}),
            ("reprojectlayer", {"INPUT": self.layer.id(), "TARGET_CRS": "/tmp/override"}),
            ("buffer", {"INPUT": self.layer.id(), "DISTANCE": True}),
            ("buffer", {"INPUT": self.layer.id(), "DISTANCE": 5, "SEGMENTS": 1.5}),
        ]
        for algorithm, values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.processing(algorithm, values)

    def test_projected_foot_units_are_explicit_in_approval(self):
        self.layer.setCrs(QgsCoordinateReferenceSystem("EPSG:2263"))
        plan = self.processing("buffer", {"INPUT": self.layer.id(), "DISTANCE": 5})
        self.assertIn("feet", plan.description.lower())

    def test_visibility_and_zoom_change_real_view_state(self):
        self.iface.setActiveLayer = self.iface.set_active_layer
        self.iface.canvas.setDestinationCrs(self.layer.crs())
        for visible in (False, True):
            result = self.run_plan(self.executor.prepare("set_layer_visibility", {"layer_id": self.layer.id(), "visible": visible}))
            self.assertTrue(result["ok"])
            self.assertEqual(self.project.layerTreeRoot().findLayer(self.layer.id()).itemVisibilityChecked(), visible)
        self.assertTrue(self.run_plan(self.executor.prepare("zoom_to_layer", {"layer_id": self.layer.id()}))["ok"])
        self.assertTrue(self.iface.canvas.extent().contains(self.layer.extent()))

    def test_metadata_names_are_bounded_and_credentials_redacted(self):
        self.layer.setName("postgres://fixture:privatepass@example.invalid/data " + "long name " * 1000)
        result = self.run_plan(self.executor.prepare("inspect_layer", {"layer_id": self.layer.id()}))
        encoded = json.dumps(result)
        self.assertNotIn("privatepass", encoded)
        self.assertLessEqual(len(result["layer"]["name"]), 256)
        self.assertNotIn("source", result["layer"])

    def test_no_geometry_table_cannot_be_buffered(self):
        table = QgsVectorLayer("None?field=id:integer&crs=EPSG:3857", "table", "memory")
        self.project.addMapLayer(table)
        with self.assertRaises(ValueError):
            self.processing("buffer", {"INPUT": table.id(), "DISTANCE": 5})


if __name__ == "__main__":
    unittest.main()
