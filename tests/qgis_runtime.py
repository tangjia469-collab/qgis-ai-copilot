"""Portable QGIS test initialization and synthetic, non-geographic fixtures."""

import os
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
    QgsProject, QgsVectorLayer,
)


def configure_prefix():
    prefix = os.environ.get("QGIS_PREFIX_PATH")
    mac_bundle = Path("/Applications/QGIS.app")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
    elif mac_bundle.exists():
        QgsApplication.setPrefixPath(str(mac_bundle), True)


def synthetic_project():
    project = QgsProject.instance()
    project.clear()
    project.setTitle("Synthetic test project")
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    polygons = QgsVectorLayer(
        "Polygon?crs=EPSG:3857&field=id:integer&field=name:string",
        "example_polygons", "memory",
    )
    for number, wkt in enumerate([
        "POLYGON((0 0,10 0,10 10,0 10,0 0))",
        "POLYGON((20 0,30 0,30 10,20 10,20 0))",
    ], 1):
        feature = QgsFeature(polygons.fields())
        feature.setAttributes([number, f"Example {number}"])
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        polygons.dataProvider().addFeatures([feature])
    polygons.updateExtents()
    reference = QgsVectorLayer("Point?crs=EPSG:3857", "example_reference", "memory")
    project.addMapLayers([polygons, reference])
    return project, polygons
