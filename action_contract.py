"""Shape-only player action contract; placement and strategy are separate."""
from state import PLANT_NAMES


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
