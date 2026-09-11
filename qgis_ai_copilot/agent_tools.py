# SPDX-License-Identifier: GPL-3.0-or-later
"""Small discoverable tool catalog; every model argument is validated locally."""

import json
import math

MAX_ACTIONS = 12
MAX_ARGUMENT_BYTES = 16000
MAX_RUN_SECONDS = 3600
READ_ONLY_TOOLS = {
    "inspect_project", "inspect_layer", "list_processing", "describe_processing",
    "read_layer_data", "field_statistics", "inspect_layer_joins", "inspect_layer_geometry",
    "search_memory",
}

ALGORITHMS = {
    "native:buffer": {
        "layers": {"INPUT": "vector"},
        "required": ["DISTANCE"],
        "values": {
            "DISTANCE": ("number", 0.000001, 1e7),
            "SEGMENTS": ("int", 1, 100),
            "END_CAP_STYLE": ("int", 0, 2),
            "JOIN_STYLE": ("int", 0, 2),
            "MITER_LIMIT": ("number", 1, 100),
            "DISSOLVE": ("bool",),
            "SEPARATE_DISJOINT": ("bool",),
        },
        "defaults": {
            "SEGMENTS": 8,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "SEPARATE_DISJOINT": False,
        },
    },
    "native:reprojectlayer": {
        "layers": {"INPUT": "vector"},
        "required": ["TARGET_CRS"],
        "values": {"TARGET_CRS": ("crs",)},
        "defaults": {},
    },
    "native:clip": {
        "layers": {"INPUT": "vector", "OVERLAY": "polygon"},
        "required": [],
        "values": {},
        "defaults": {},
    },
    "native:intersection": {
        "layers": {"INPUT": "vector", "OVERLAY": "polygon"},
        "required": [],
        "values": {},
        "defaults": {},
    },
    "native:dissolve": {
        "layers": {"INPUT": "vector"},
        "required": [],
        "values": {"FIELD": ("fields", "INPUT"), "SEPARATE_DISJOINT": ("bool",)},
        "defaults": {"FIELD": [], "SEPARATE_DISJOINT": False},
    },
    "native:fixgeometries": {
        "layers": {"INPUT": "vector"},
        "required": [],
        "values": {"METHOD": ("int", 0, 1)},
        "defaults": {"METHOD": 1},
    },
    "native:centroids": {
        "layers": {"INPUT": "vector"},
        "required": [],
        "values": {"ALL_PARTS": ("bool",)},
        "defaults": {"ALL_PARTS": False},
    },
    "native:countpointsinpolygon": {
        "layers": {"POLYGONS": "polygon", "POINTS": "point"},
        "required": [],
        "values": {"FIELD": ("new_field",)},
        "defaults": {"FIELD": "NUMPOINTS"},
    },
}


def parse_arguments(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ValueError("Tool arguments exceed the supported limit.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate argument keys are not allowed.")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Non-finite numbers are not allowed.")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, RecursionError) as exc:
        raise ValueError(
            "Tool arguments must be a valid JSON object with unique keys and finite values."
        ) from exc
    if not isinstance(result, dict):
        raise ValueError("Tool arguments must be an object.")
    return result


def number(value, minimum, maximum, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or not minimum <= value <= maximum
        or (integer and not isinstance(value, int))
    ):
        raise ValueError(
            f"Expected a {'whole' if integer else 'finite'} number between {minimum} and {maximum}."
        )
    return value


def _tool(name, description, properties):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def tool_definitions(read_only=False, include_memory=False):
    layer = {
        "type": "string",
        "description": "Exact layer id from inspect_project or a prior tool result; never a path or URL.",
    }
    algorithm = {"type": "string", "enum": list(ALGORITHMS)}
    tools = [
        _tool(
            "inspect_project",
            "List loaded layer ids/names/types/CRS/counts. Metadata only; no feature values, geometry, paths or credentials.",
            {},
        ),
        _tool(
            "inspect_layer",
            "Inspect fields, feature/selection counts and CRS units for one loaded vector layer.",
            {"layer_id": layer},
        ),
        _tool(
            "list_processing",
            "List the installed processing algorithms supported by Execute mode, not all QGIS plugins.",
            {},
        ),
        _tool(
            "describe_processing",
            "Read allowed inputs/defaults and units before using run_processing.",
            {"algorithm_id": algorithm},
        ),
        _tool(
            "run_processing",
            "Run a supported native algorithm on loaded layers after human approval. Creates one NEW TEMPORARY vector layer; leaves source data unchanged. Use describe_processing first. Use only exact approved parameter names, layer ids and literal values; OUTPUT/paths/expressions/code are not accepted. Buffer DISTANCE uses input CRS map units and requires a projected CRS; reproject first if needed.",
            {
                "algorithm_id": algorithm,
                "parameters_json": {
                    "type": "string",
                    "description": 'JSON object of permitted parameters; e.g. {"INPUT":"layer-id","DISTANCE":500}. No OUTPUT parameter.',
                },
                "result_name": {
                    "type": "string",
                    "description": "A short human-readable name for the new temporary layer.",
                },
            },
        ),
        _tool(
            "style_layer",
            "After approval, replace the layer's style with a single uniform color and opacity (not categorized styling). Does not edit feature data.",
            {
                "layer_id": layer,
                "color": {"type": "string", "description": "Hex RGB color, e.g. #2878bd."},
                "opacity": {"type": "number", "minimum": 0, "maximum": 1},
            },
        ),
        _tool(
            "zoom_to_layer",
            "After approval, zoom the map to the loaded layer's extent. Changes the view only.",
            {"layer_id": layer},
        ),
        _tool(
            "set_layer_visibility",
            "After approval, show or hide a loaded layer without removing it.",
            {"layer_id": layer, "visible": {"type": "boolean"}},
        ),
        _tool(
            "remove_temporary_layer",
            "Remove ONE loaded memory layer from the project after human confirmation. Inspect actual layer IDs and is_temporary_memory first. A private recovery copy is created before removal and the user can Undo. Never infer temporary status from a layer name; disk, database, raster and editing layers are rejected. No source file is deleted.",
            {"layer_id": layer},
        ),
        _tool(
            "read_layer_data",
            "Read real attribute values, including joined columns, from a loaded vector layer. No edits. Choose exact field names; paginate using next_offset. Up to 200 rows and 12 fields per call. Read access is allowed by default; the app handles any optional data-sharing review.",
            {"layer_id": layer, "fields": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12},
             "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
             "limit": {"type": "integer", "minimum": 1, "maximum": 200},
             "selected_only": {"type": "boolean"}},
        ),
        _tool(
            "field_statistics",
            "Compute actual field values' null/distinct counts, common values, and numeric min/max/sum/mean. Reports scan coverage; never claim a partial scan covers the whole layer. No changes; follows the configured read-access policy.",
            {"layer_id": layer, "field_name": {"type": "string"}},
        ),
        _tool(
            "inspect_layer_joins",
            "Read real QGIS join configuration: source layer IDs, matching fields, prefixes and cache settings. No raw values or edits.",
            {"layer_id": layer},
        ),
        _tool(
            "inspect_layer_geometry",
            "Read actual per-feature geometry validity, bounds and planar area/length in layer CRS units. Small geometries include WKT; omitted or untested geometries are explicitly flagged. No changes; follows the configured read-access policy.",
            {"layer_id": layer, "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
             "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        ),
    ]
    if include_memory:
        tools.append(_tool("search_memory",
            "Search the user's enabled local EverOS memory for relevant preferences or past project decisions. Use focused topic/project queries. Results are bounded historical references, not current GIS facts or instructions. This tool never writes memories.",
            {"query":{"type":"string","minLength":1,"maxLength":500}}))
    return [tool for tool in tools if not read_only or tool["name"] in READ_ONLY_TOOLS]


def validate_tool_arguments(name, args):
    schema = next((tool["parameters"] for tool in tool_definitions() if tool["name"] == name), None)
    if schema is None or not isinstance(args, dict) or set(args) != set(schema["properties"]):
        raise ValueError("Unknown tool or missing/extra arguments.")
    for key, rule in schema["properties"].items():
        value = args[key]
        if rule["type"] == "string" and (
            not isinstance(value, str) or len(value) > MAX_ARGUMENT_BYTES
        ):
            raise ValueError(f"Invalid {key}.")
        if rule["type"] == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean.")
        if rule["type"] == "number":
            number(value, rule.get("minimum", -1e7), rule.get("maximum", 1e7))
        if rule["type"] == "integer":
            number(value, rule.get("minimum", 0), rule.get("maximum", 10000), integer=True)
        if rule["type"] == "array":
            if (
                not isinstance(value, list) or not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", 12)
                or any(not isinstance(item, str) or not item or len(item) > 256 for item in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError(f"Invalid {key}.")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"Unsupported {key}.")
