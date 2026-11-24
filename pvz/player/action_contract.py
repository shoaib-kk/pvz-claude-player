"""Shape-only player action contract; placement and strategy are separate."""
from pvz.game.state import PLANT_NAMES


def action_schema(names=None):
    names = list(dict.fromkeys(PLANT_NAMES if names is None else names))
    common = {"row": {"type": "integer", "minimum": 0, "maximum": 5},
              "col": {"type": "integer", "minimum": 0, "maximum": 8},
              "id": {"type": "integer", "minimum": 1},
              "independent": {"type": "boolean"},
              "group": {"type": "integer", "minimum": 0}}
    branches = []
    for kind in ("plant", "shovel", "break_vase"):
        if kind == "plant" and not names:
            continue
        properties = {**common, "type": {"type": "string", "enum": [kind]}}
        required = ["type", "row", "col"]
        if kind == "plant":
            properties["seed"] = {"type": "string", "enum": names}
            required.append("seed")
        branches.append({"type": "object", "properties": properties,
                         "required": required, "additionalProperties": False})
    return {"anyOf": branches}


def check_action(action):
    """Validate before queue mutation, including callers without a schema-aware CLI."""
    if not isinstance(action, dict) or action.get("type") not in ("plant", "shovel", "break_vase"):
        raise ValueError("unknown action type")
    for field, maximum in (("row", 5), ("col", 8)):
        if type(action.get(field)) is not int or not 0 <= action[field] <= maximum:
            raise ValueError(f"{field} must be an integer from 0 to {maximum}")
    if action["type"] == "plant" and action.get("seed") not in PLANT_NAMES:
        raise ValueError("plant requires seed to be a packet name, never a slot number")
    if action["type"] != "plant" and "seed" in action:
        raise ValueError("only plant actions take a seed")


def validate_schema(value, schema):
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                validate_schema(value, branch)
                return
            except ValueError:
                pass
        raise ValueError("value does not match any action variant")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in schema and type(value) is not types[schema["type"]]:
        raise ValueError(f"expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"invalid enum: {value}")
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= value.keys():
            raise ValueError("missing required fields")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not value.keys() <= properties.keys():
            raise ValueError("unexpected fields")
        for k, item in value.items():
            if k in properties:
                validate_schema(item, properties[k])
    elif isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError("too many items")
        for item in value:
            validate_schema(item, schema.get("items", {}))
    elif type(value) is int and value < schema.get("minimum", value):
        raise ValueError("integer below minimum")
    elif type(value) is int and value > schema.get("maximum", value):
        raise ValueError("integer above maximum")
