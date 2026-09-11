# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, read-only attribute, join and geometry inspection."""

from collections import Counter
import json
import math
import re
import time

from qgis.PyQt.QtCore import QDate, QDateTime, QTime, Qt
from qgis.core import QgsFeatureRequest, QgsVariantUtils, QgsWkbTypes, QgsUnitTypes

from .storage import _redact_context_text, _SENSITIVE_CONTEXT_KEYS


MAX_SCAN = 10000
MAX_RESULT_BYTES = 64000
MAX_READ_SECONDS = 5
DATA_TOOLS = {"read_layer_data", "field_statistics", "inspect_layer_geometry"}
INSPECTION_TOOLS = DATA_TOOLS | {"inspect_layer_joins"}


def validate_fields(layer, names):
    for name in names:
        if layer.fields().indexFromName(name) < 0:
            raise ValueError(f"Field does not exist: {name}")
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        normalized = re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")
        compact = normalized.replace("_", "")
        if set(normalized.split("_")) & _SENSITIVE_CONTEXT_KEYS or any(
            part in compact
            for part in (
                "password",
                "secret",
                "apikey",
                "authorization",
                "credential",
                "accesstoken",
                "refreshtoken",
                "sourceurl",
                "sourceuri",
                "filepath",
            )
        ):
            raise ValueError("Credential/source fields are excluded from model data access.")


def data_scope(name, args, layer):
    return {
        "tool": name,
        "layer_id": args["layer_id"],
        "fields": args.get("fields", [args["field_name"]] if "field_name" in args else []),
        "all_rows": not args.get("selected_only", False),
        "selected_ids": sorted(layer.selectedFeatureIds()) if args.get("selected_only") else [],
        "geometry": name == "inspect_layer_geometry",
    }


def _value(value):
    if QgsVariantUtils.isNull(value):
        return None, False
    if isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        return (value, False) if math.isfinite(value) else (None, True)
    if isinstance(value, (QDate, QDateTime, QTime)):
        return value.toString(Qt.ISODate), False
    if isinstance(value, str):
        clean = _redact_context_text(value)
        return clean[:2048], clean != value or len(clean) > 2048
    return None, True


def _request(layer, fields=None, limit=201, selected_only=False, geometry=False):
    request = QgsFeatureRequest()
    if fields is not None:
        request.setSubsetOfAttributes(fields, layer.fields())
    if not geometry:
        request.setFlags(request.flags() | QgsFeatureRequest.NoGeometry)
    if selected_only:
        request.setFilterFids(layer.selectedFeatureIds())
    request.setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause("$id")]))
    request.setLimit(limit)
    return request


def _page(layer, args, transform, geometry=False):
    offset, limit = args["offset"], args["limit"]
    selected = args.get("selected_only", False)
    rows = []
    size = 0
    has_more = False
    stop_reason = None
    started = time.monotonic()
    request = _request(layer, args.get("fields", []), offset + limit + 1, selected, geometry)
    if selected and not layer.selectedFeatureCount():
        iterator = iter(())
    else:
        iterator = layer.getFeatures(request)
    try:
        for index, feature in enumerate(iterator):
            if time.monotonic() - started > MAX_READ_SECONDS:
                has_more, stop_reason = True, "time_limit"
                break
            if index < offset:
                continue
            if len(rows) == limit:
                has_more = True
                break
            row = transform(feature)
            byte_count = len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode())
            if size + byte_count > MAX_RESULT_BYTES:
                has_more, stop_reason = True, "output_limit"
                break
            rows.append(row)
            size += byte_count
    finally:
        if hasattr(iterator, "close"):
            iterator.close()
    no_progress = bool(stop_reason and not rows)
    result = {
        "ok": not no_progress,
        "layer_id": layer.id(),
        "feature_count": layer.featureCount(),
        "selected_only": selected,
        "offset": offset,
        "returned": len(rows),
        "has_more": has_more,
        "next_offset": offset + len(rows) if has_more and rows else None,
        "stop_reason": stop_reason,
        "rows": rows,
    }
    if no_progress:
        result["error"] = (
            "The read limit was reached before a row could be returned. "
            "Do not repeat this page unchanged; narrow the selection/fields or use field statistics."
        )
    return result


def read_layer_data(layer, args):
    fields = args["fields"]

    def row(feature):
        attributes = {}
        changed = []
        for field in fields:
            attributes[field], limited = _value(feature[field])
            if limited:
                changed.append(field)
        return {
            "feature_id": feature.id(),
            "attributes": attributes,
            "redacted_or_omitted_fields": changed,
        }

    result = _page(layer, args, row)
    result["fields"] = fields
    return result


def field_statistics(layer, args):
    field = args["field_name"]
    request = _request(layer, [field], MAX_SCAN + 1)
    counts = Counter()
    labels = {}
    numbers = []
    scanned = nulls = altered = 0
    complete = True
    stop_reason = None
    started = time.monotonic()
    iterator = layer.getFeatures(request)
    try:
        for feature in iterator:
            if scanned >= MAX_SCAN:
                complete = False
                stop_reason = "feature_limit"
                break
            if time.monotonic() - started > MAX_READ_SECONDS:
                complete = False
                stop_reason = "time_limit"
                break
            value, limited = _value(feature[field])
            scanned += 1
            altered += bool(limited)
            if limited and value is None:
                continue
            if value is None:
                nulls += 1
                continue
            key = json.dumps(value, ensure_ascii=False)
            counts[key] += 1
            labels[key] = value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numbers.append(value)
    finally:
        iterator.close()
    return {
        "ok": True,
        "layer_id": layer.id(),
        "field_name": field,
        "feature_count": layer.featureCount(),
        "scanned_features": scanned,
        "complete": complete,
        "stop_reason": stop_reason,
        "null_count": nulls,
        "redacted_or_omitted_count": altered,
        "distinct_count": len(counts) if not altered else None,
        "numeric_count": len(numbers),
        "min": min(numbers) if numbers else None,
        "max": max(numbers) if numbers else None,
        "sum": math.fsum(numbers) if numbers else None,
        "mean": math.fsum(numbers) / len(numbers) if numbers else None,
        "common_values": [{"value": labels[k], "count": n} for k, n in counts.most_common(10)],
    }


def inspect_layer_joins(layer, _args):
    joins = []
    for join in layer.vectorJoins()[:20]:
        source = join.joinLayer()
        joins.append(
            {
                "join_layer_id": join.joinLayerId(),
                "join_layer_name": _redact_context_text(source.name())[:256] if source else None,
                "target_field": join.targetFieldName(),
                "join_field": join.joinFieldName(),
                "prefix": join.prefix(),
                "field_subset": join.joinFieldNamesSubset(),
                "memory_cache": join.isUsingMemoryCache(),
                "editable": join.isEditable(),
            }
        )
    return {
        "ok": True,
        "layer_id": layer.id(),
        "joins": joins,
        "truncated": len(layer.vectorJoins()) > 20,
    }


def inspect_layer_geometry(layer, args):
    def row(feature):
        geometry = feature.geometry()
        missing = geometry.isNull()
        empty = geometry.isEmpty()
        coordinates = 0 if missing else geometry.constGet().nCoordinates()
        result = {
            "feature_id": feature.id(),
            "is_null": missing,
            "is_empty": empty,
            "type": QgsWkbTypes.displayString(geometry.wkbType()),
            "is_valid": geometry.isGeosValid() if not missing and coordinates <= 100000 else None,
            "validation_omitted": missing or coordinates > 100000,
            "planar_area": geometry.area() if not empty else 0,
            "planar_length": geometry.length() if not empty else 0,
            "vertex_count": coordinates,
            "bounds": None,
            "wkt": None,
            "wkt_omitted": missing or coordinates > 64,
        }
        if not empty:
            box = geometry.boundingBox()
            result["bounds"] = [box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()]
        if not missing and coordinates <= 64:
            wkt = geometry.asWkt(8)
            if len(wkt) <= 6000:
                result["wkt"] = wkt
            else:
                result["wkt_omitted"] = True
        return result

    result = _page(layer, args, row, geometry=True)
    result["features"] = result.pop("rows")
    result["crs"] = layer.crs().authid()
    result["map_units"] = QgsUnitTypes.toString(layer.crs().mapUnits())
    result["measurement_note"] = (
        "Planar area is in squared CRS map units; not ellipsoidal/geodesic area."
    )
    return result


READERS = {
    "read_layer_data": read_layer_data,
    "field_statistics": field_statistics,
    "inspect_layer_joins": inspect_layer_joins,
    "inspect_layer_geometry": inspect_layer_geometry,
}
