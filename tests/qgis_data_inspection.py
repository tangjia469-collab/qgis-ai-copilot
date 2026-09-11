"""Read-only inspection of real synthetic rows, joins and geometries."""

import os
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsApplication,
    QgsField,
    QgsProject,
    QgsVectorLayer,
    QgsVectorLayerJoinInfo,
    QgsFeature,
)

from qgis_ai_copilot.agent_tools import tool_definitions
from qgis_ai_copilot.executor import QgisToolExecutor
from qgis_ai_copilot.execution import ExecuteSession
from qgis_ai_copilot.protocol import RouterProfile
from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface


class DataInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.project, self.layer = synthetic_project()
        self.iface = FakeIface()
        self.iface.set_active_layer(self.layer)
        self.executor = QgisToolExecutor(self.iface)
        self.before = [
            (f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()
        ]

    def tearDown(self):
        self.executor.cancel()
        self.iface.window.close()
        self.project.clear()

    def run_tool(self, name, args, shares_data=True):
        self.assertIn(
            name, [t["name"] for t in tool_definitions()], "Missing actual-data inspection tool"
        )
        plan = self.executor.prepare(name, args)
        self.assertFalse(plan.mutating)
        self.assertEqual(plan.shares_data, shares_data)
        result = []
        self.executor.execute(plan, result.append)
        self.assertTrue(result)
        self.assertEqual(
            self.before,
            [(f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()],
        )
        return result[0]

    def test_rows_are_real_paginated_values_not_schema(self):
        first = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["id", "name"],
                "offset": 0,
                "limit": 1,
                "selected_only": False,
            },
        )
        self.assertEqual(first["rows"][0]["attributes"], {"id": 1, "name": "Example 1"})
        self.assertTrue(first["has_more"])
        second = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["id", "name"],
                "offset": first["next_offset"],
                "limit": 1,
                "selected_only": False,
            },
        )
        self.assertEqual(second["rows"][0]["attributes"], {"id": 2, "name": "Example 2"})
        self.assertFalse(second["has_more"])

    def test_selection_is_observed_without_being_changed(self):
        fid = self.before[1][0]
        self.layer.selectByIds([fid])
        result = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["name"],
                "offset": 0,
                "limit": 20,
                "selected_only": True,
            },
        )
        self.assertEqual([r["feature_id"] for r in result["rows"]], [fid])
        self.assertEqual(self.layer.selectedFeatureIds(), [fid])

    def test_empty_selection_returns_no_rows(self):
        result = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["id"],
                "offset": 0,
                "limit": 20,
                "selected_only": True,
            },
        )
        self.assertEqual(result["rows"], [])
        self.assertFalse(result["has_more"])

    def test_selection_changed_during_approval_is_rejected(self):
        self.layer.selectByIds([self.before[0][0]])
        plan = self.executor.prepare(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["id"],
                "offset": 0,
                "limit": 20,
                "selected_only": True,
            },
        )
        self.layer.selectByIds([self.before[1][0]])
        result = []
        with self.assertRaisesRegex(ValueError, "selection|Selection"):
            self.executor.execute(plan, result.append)
        self.assertEqual(result, [])

    def test_consent_does_not_expand_to_raw_rows_or_new_selection(self):
        session = ExecuteSession(self.iface, RouterProfile(adapter="responses"), read_only=True)
        self.addCleanup(session.cancel)
        self.addCleanup(session.deleteLater)
        stats = self.executor.prepare(
            "field_statistics", {"layer_id": self.layer.id(), "field_name": "id"}
        )
        session._approved_data_scopes.append(stats.data_scope)
        args = {
            "layer_id": self.layer.id(),
            "fields": ["id"],
            "offset": 0,
            "limit": 1,
            "selected_only": False,
        }
        rows = self.executor.prepare("read_layer_data", args)
        self.assertFalse(session._data_is_approved(rows.data_scope))
        self.layer.selectByIds([self.before[0][0]])
        args["selected_only"] = True
        selected = self.executor.prepare("read_layer_data", args)
        session._approved_data_scopes.append(selected.data_scope)
        self.assertTrue(session._data_is_approved(selected.data_scope))
        self.layer.selectByIds([self.before[1][0]])
        different = self.executor.prepare("read_layer_data", args)
        self.assertFalse(session._data_is_approved(different.data_scope))

    def test_paging_can_reuse_consent_but_changed_layer_cannot(self):
        session = ExecuteSession(self.iface, RouterProfile(adapter="responses"), read_only=True)
        self.addCleanup(session.cancel)
        self.addCleanup(session.deleteLater)
        args = {
            "layer_id": self.layer.id(),
            "fields": ["id", "name"],
            "offset": 0,
            "limit": 1,
            "selected_only": False,
        }
        first = self.executor.prepare("read_layer_data", args)
        session._approved_data_scopes.append(first.data_scope)
        args.update(offset=1, fields=["id"])
        page = self.executor.prepare("read_layer_data", args)
        self.assertTrue(session._data_is_approved(page.data_scope))
        self.layer.setSubsetString('"id" = 2')
        changed = self.executor.prepare("read_layer_data", args)
        self.assertFalse(session._data_is_approved(changed.data_scope))

    def test_timeout_before_offset_reports_no_progress_instead_of_looping(self):
        with patch("qgis_ai_copilot.inspection.time.monotonic", side_effect=[0, 0, 6]):
            result = self.run_tool(
                "read_layer_data",
                {
                    "layer_id": self.layer.id(),
                    "fields": ["id"],
                    "offset": 1,
                    "limit": 1,
                    "selected_only": False,
                },
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["stop_reason"], "time_limit")
        self.assertIsNone(result["next_offset"])
        self.assertIn("narrow", result["error"].lower())

    def test_statistics_reports_why_scan_is_partial(self):
        with patch("qgis_ai_copilot.inspection.MAX_SCAN", 1):
            result = self.run_tool(
                "field_statistics", {"layer_id": self.layer.id(), "field_name": "id"}
            )
        self.assertFalse(result["complete"])
        self.assertEqual(result["scanned_features"], 1)
        self.assertEqual(result.get("stop_reason"), "feature_limit")
        with patch("qgis_ai_copilot.inspection.time.monotonic", side_effect=[0, 0, 6]):
            result = self.run_tool(
                "field_statistics", {"layer_id": self.layer.id(), "field_name": "id"}
            )
        self.assertFalse(result["complete"])
        self.assertEqual(result.get("stop_reason"), "time_limit")

    def test_credential_and_source_field_name_variants_are_rejected(self):
        fields = ["api key", "apiKey", "source_url", "sourceURI", "auth token", "file_path"]
        self.layer.dataProvider().addAttributes(
            [QgsField(name, QVariant.String) for name in fields]
        )
        self.layer.updateFields()
        for name in fields:
            with self.subTest(field=name), self.assertRaises(ValueError):
                self.executor.prepare(
                    "read_layer_data",
                    {
                        "layer_id": self.layer.id(),
                        "fields": [name],
                        "offset": 0,
                        "limit": 20,
                        "selected_only": False,
                    },
                )

    def test_statistics_scan_actual_values_and_report_coverage(self):
        result = self.run_tool(
            "field_statistics", {"layer_id": self.layer.id(), "field_name": "id"}
        )
        self.assertEqual(result["scanned_features"], 2)
        self.assertTrue(result["complete"])
        self.assertEqual(result["distinct_count"], 2)
        self.assertEqual(result["sum"], 3)
        self.assertEqual(result["mean"], 1.5)

    def test_join_configuration_and_joined_values_are_read(self):
        joined = QgsVectorLayer("None?field=id:integer&field=green_area:double", "areas", "memory")
        for key, value in ((1, 42.5), (2, 76.0)):
            f = QgsFeature(joined.fields())
            f.setAttributes([key, value])
            joined.dataProvider().addFeatures([f])
        self.project.addMapLayer(joined)
        join = QgsVectorLayerJoinInfo()
        join.setJoinLayer(joined)
        join.setTargetFieldName("id")
        join.setJoinFieldName("id")
        join.setPrefix("area_")
        self.layer.addJoin(join)
        self.before = [
            (f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()
        ]
        result = self.run_tool(
            "inspect_layer_joins", {"layer_id": self.layer.id()}, shares_data=False
        )
        self.assertEqual(result["joins"][0]["join_layer_id"], joined.id())
        self.assertEqual(result["joins"][0]["target_field"], "id")
        rows = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["id", "area_green_area"],
                "offset": 0,
                "limit": 20,
                "selected_only": False,
            },
        )
        self.assertEqual([r["attributes"]["area_green_area"] for r in rows["rows"]], [42.5, 76.0])

    def test_geometry_checks_are_real_and_units_are_explicit(self):
        result = self.run_tool(
            "inspect_layer_geometry", {"layer_id": self.layer.id(), "offset": 0, "limit": 20}
        )
        self.assertEqual(len(result["features"]), 2)
        self.assertTrue(all(r["is_valid"] for r in result["features"]))
        self.assertEqual([r["planar_area"] for r in result["features"]], [100, 100])
        self.assertIn("meters", result["map_units"])
        self.assertEqual(result["features"][0]["bounds"], [0, 0, 10, 10])

    def test_bad_fields_and_excessive_requests_are_rejected(self):
        self.assertIn("read_layer_data", [t["name"] for t in tool_definitions()])
        for fields, limit in ((["missing"], 20), (["id"], 201), ([], 20)):
            with self.subTest(fields=fields, limit=limit), self.assertRaises(ValueError):
                self.executor.prepare(
                    "read_layer_data",
                    {
                        "layer_id": self.layer.id(),
                        "fields": fields,
                        "offset": 0,
                        "limit": limit,
                        "selected_only": False,
                    },
                )

    def test_null_values_are_json_null_and_credentials_are_not_shared(self):
        self.layer.dataProvider().addAttributes(
            [QgsField("nullable", QVariant.String), QgsField("password", QVariant.String)]
        )
        self.layer.updateFields()
        self.before = [
            (f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()
        ]
        result = self.run_tool(
            "read_layer_data",
            {
                "layer_id": self.layer.id(),
                "fields": ["nullable"],
                "offset": 0,
                "limit": 20,
                "selected_only": False,
            },
        )
        self.assertIsNone(result["rows"][0]["attributes"]["nullable"])
        with self.assertRaises(ValueError):
            self.executor.prepare(
                "read_layer_data",
                {
                    "layer_id": self.layer.id(),
                    "fields": ["password"],
                    "offset": 0,
                    "limit": 20,
                    "selected_only": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
