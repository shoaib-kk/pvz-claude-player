"""Monitor measurable goals chosen by the player; never enqueue or choose moves."""
import copy
from pvz.game.state import PLANT_NAMES

OBJECTIVES_SCHEMA = {"type": "array", "maxItems": 3, "items": {
    "type": "object", "properties": {
        "label": {"type": "string"}, "seed": {"type": "string", "enum": PLANT_NAMES},
        "count": {"type": "integer", "minimum": 1, "maximum": 45},
        "row": {"type": "integer", "minimum": 0, "maximum": 5},
        "col": {"type": "integer", "minimum": 0, "maximum": 8},
        "before_wave": {"type": "integer", "minimum": 1}},
    "required": ["label", "seed", "count"], "additionalProperties": False}}

OBJECTIVES_RULE = ("\nAlso choose up to 3 measurable objectives yourself in objectives (or []): "
                   "a packet seed name and completed planting count, optionally a row, col, and "
                   "strict before_wave deadline. They monitor your own plan, do not execute it. "
                   "Only specify known targets; omit row/col when not yet known. You will see "
                   "completed and currently present counts. Revise your strategy yourself if needed.")


class PlanProgress:
    def __init__(self, objectives=()):
        self.objectives = copy.deepcopy(list(objectives or [])[:3])
        self.completed = []

    def purchased(self, action, state):
        self.completed.append({**action, "wave": state.get("wave", [0])[0]})

    @staticmethod
    def matches(goal, item):
        return (goal["seed"] == item.get("seed", item.get("type"))
                and all(field not in goal or goal[field] == item.get(field) for field in ("row", "col")))

    def status(self, state):
        wave = state.get("wave", [0])[0]
        result = []
        for goal in self.objectives:
            done = [a for a in self.completed if self.matches(goal, a)]
            on_time = [a for a in done if "before_wave" not in goal or a["wave"] < goal["before_wave"]]
            met = len(on_time) >= goal["count"]
            result.append({**goal, "completed": len(done), "completed_on_time": len(on_time),
                           "currently_present": sum(self.matches(goal, p) for p in state.get("plants", [])),
                           "status": "met" if met else "deadline missed" if (
                               "before_wave" in goal and wave >= goal["before_wave"]) else "pending"})
        return result

    def report(self, state):
        rows = self.status(state)
        if not rows:
            return ""
        lines = ["Your measurable objectives (monitoring only; completed does not mean still alive or proven useful):"]
        for n, row in enumerate(rows, 1):
            deadline = f"; required before wave {row['before_wave']}" if "before_wave" in row else ""
            lines.append(f"  {n}. {row['label']}: {row['status']}; completed "
                         f"{row['completed_on_time']}/{row['count']} on time, "
                         f"{row['completed']} total; currently present {row['currently_present']}{deadline}.")
        return "\n".join(lines)
