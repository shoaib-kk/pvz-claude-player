"""The player's own lessons journal.

After every finished level the player looks back at what happened (a factual
timeline the agent records: loadout, its own pre-level plan, plants lost, mowers used,
final board) and rewrites its lessons in its own words. Lessons are kept in two parts:
general ones, and ones for the current situation (night, pool, conveyor...), so that
lessons for one kind of level don't crowd out another's. The journal carries across
levels and runs and goes into the player's prompts, so strategy is learned rather than
hard-coded. It lives in journal/ (git-ignored); journal/lessons.md is a readable copy
for the video.
"""
import json
from datetime import datetime
from pathlib import Path

from plant_info import POTATO_MINE_ARM_SECONDS

SHOOTERS = {"peashooter", "snow_pea", "repeater", "gatling_pea", "threepeater", "split_pea",
            "cactus", "starfruit", "puff_shroom", "scaredy_shroom", "fume_shroom", "gloom_shroom",
            "cabbage_pult", "kernel_pult", "melon_pult", "winter_melon", "sea_shroom", "cattail"}

ROOT = Path(__file__).resolve().parent
MAX_LESSONS = 20          # general lessons
MAX_SITUATION = 10        # lessons per situation
# A new situation section starts as a copy of a related one: fog levels are night levels with a pool.
SEED_FROM = {"fog": "night", "fog conveyor": "night"}

REFLECT_SYSTEM = """You are the player in a run of Plants vs. Zombies, reviewing a level you just finished.
You keep a short journal of lessons that you will read before future levels. It has general lessons
(true for any level) and lessons for the current kind of level (the situation named in the request).
Look at what happened, and at the plan you wrote before the level: did the plan work, and did you
stick to it? Then rewrite both lists: keep lessons that still hold, fix or merge ones this level
proved wrong or incomplete, and add what you learned now. Put a lesson in the situation list if it
only applies to this kind of level.
Lessons must be concrete and in your own words (plant placement, timing, economy,
specific zombies), about things you control: which plants you bring, and what you plant or
shovel where and when. Lawn mowers fire by themselves; plants can't be moved.
At most %d general and %d situation lessons, one short sentence per lesson, most important first.
Also write a one-sentence summary of why you won or lost this level.
Answer with JSON only.""" % (MAX_LESSONS, MAX_SITUATION)

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "general_lessons": {"type": "array", "items": {"type": "string"}},
        "situation_lessons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "general_lessons", "situation_lessons"],
    "additionalProperties": False,
}


def situation_of(info):
    """Journal section for a level: its special mode, conveyor, or terrain."""
    if not info:
        return None
    if info.get("special"):
        return info["special"]
    if info.get("conveyor"):
        return f"{info.get('terrain', 'day')} conveyor"
    return info.get("terrain")


def _clean(items, limit):
    return [str(x).strip() for x in (items or []) if str(x).strip()][:limit]


class Journal:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else ROOT / "journal"
        self.path = self.folder / "lessons.json"
        self.data = {"lessons": [], "sections": {}, "history": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        self.data.setdefault("sections", {})

    @property
    def lessons(self):
        """General lessons."""
        return list(self.data.get("lessons", []))

    def section(self, situation):
        return list(self.data["sections"].get(situation, [])) if situation else []

    def seed_section(self, situation):
        """The first time a situation with a related parent comes up (fog is a night level), start
        its section from a copy of the parent's lessons, followed by any lessons it already had."""
        parent = SEED_FROM.get(situation)
        seeded = self.data.setdefault("seeded", [])
        if not parent or situation in seeded or not self.section(parent):
            return
        merged = list(dict.fromkeys(self.section(parent) + self.section(situation)))[:MAX_SITUATION]
        self.data["sections"][situation] = merged
        seeded.append(situation)
        self.save()

    def prompt_block(self, situation=None):
        """Text appended to the player's system prompts."""
        self.seed_section(situation)
        general, special = self.lessons, self.section(situation)
        if not general and not special:
            return ("\n\nYour journal is empty for this: you haven't finished a level like it yet. "
                    "Work out what works by playing.")
        text = "\n\nYour journal - lessons you wrote yourself after earlier levels:"
        if general:
            text += "\nGeneral:\n" + "\n".join(f"- {x}" for x in general)
        if situation:
            text += f"\nFor {situation} levels:\n" + ("\n".join(f"- {x}" for x in special)
                                                      if special else "- (none yet)")
        return text

    def reflect(self, brain, level_label, outcome, report, situation=None, plan=None):
        """Ask the player to rewrite its journal. Returns the summary, or None."""
        ask = getattr(brain, "ask", None)
        if not ask:
            return None
        general = "\n".join(f"- {x}" for x in self.lessons) or "(empty)"
        special = "\n".join(f"- {x}" for x in self.section(situation)) or "(empty)"
        prompt = (f"Level {level_label} ({situation or 'unknown'} situation): you {outcome.upper()}.\n\n"
                  + (f"The plan you wrote before the level:\n{plan}\n\n" if plan else "")
                  + f"{report}\n\nYour journal before this level:\nGeneral:\n{general}\n"
                  f"For {situation or 'this kind of'} levels:\n{special}")
        effort = getattr(brain, "plan_effort", None)
        answer = (ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA, effort=effort) if effort
                  else ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA))
        lessons = _clean(answer.get("general_lessons", answer.get("lessons")), MAX_LESSONS)
        situation_lessons = _clean(answer.get("situation_lessons"), MAX_SITUATION)
        summary = str(answer.get("summary", "")).strip()
        self.data["lessons"] = lessons
        if situation:
            self.data["sections"][situation] = situation_lessons
        self.data.setdefault("history", []).append({
            "level": level_label, "outcome": outcome, "situation": situation, "summary": summary,
            "plan": plan, "lessons": lessons, "situation_lessons": situation_lessons,
            "t": datetime.now().isoformat(timespec="seconds"),
        })
        self.save()
        return summary

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        md = ["# Claude's PvZ journal", "", "## General lessons", ""]
        md += [f"{i}. {x}" for i, x in enumerate(self.lessons, 1)] or ["(none yet)"]
        for situation, items in self.data["sections"].items():
            md += ["", f"## {situation.capitalize()} levels", ""]
            md += [f"{i}. {x}" for i, x in enumerate(items, 1)] or ["(none yet)"]
        md += ["", "## Level history", ""]
        for h in self.data.get("history", []):
            md.append(f"- **{h['level']}** ({h['outcome']}, {h['t']}): {h['summary']}")
            if h.get("plan"):
                md.append("  - Plan: " + " / ".join(x.strip() for x in h["plan"].splitlines() if x.strip()))
        (self.folder / "lessons.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# Plants that disappear when they do their job, so disappearing isn't a loss.
ONE_USE = {"cherry_bomb", "jalapeno", "squash", "ice_shroom", "doom_shroom", "grave_buster",
           "coffee_bean", "blover", "tangle_kelp", "hypno_shroom", "explode_o_nut"}
MAYBE_USED = {"potato_mine"}     # exploded, or eaten while still arming - indistinguishable here


class LevelRecorder:
    """Factual timeline of one level, built from the boards sent to the player."""

    def __init__(self, level_label, loadout=None, options=None):
        self.level_label = level_label
        self.loadout = list(loadout or [])
        self.options = list(options or [])   # every plant the chooser offered
        self.events = []
        self.last = None
        self.lost_count = {}
        self.used_count = {}
        self.unarmed_mines = 0
        self.mower_wave = {}
        self.planted = {}

    def observe(self, state):
        if not state or not state.get("in_level"):
            return
        wave = state.get("wave", [0, 0])[0]
        if self.last is not None:
            before = {(p["row"], p["col"], p["type"]) for p in self.last["plants"]}
            ages = {(p["row"], p["col"], p["type"]): p.get("age") for p in self.last["plants"]}
            after = {(p["row"], p["col"], p["type"]) for p in state["plants"]}
            for row, col, kind in sorted(before - after):
                near = [z["type"] for z in state["zombies"] if z["row"] == row]
                zs = f" (zombies in that row: {', '.join(sorted(set(near)))})" if near else ""
                if kind in ONE_USE:
                    self.used_count[kind] = self.used_count.get(kind, 0) + 1
                    self.events.append(f"wave {wave}: {kind} at row {row} col {col} was used up{zs}")
                elif kind in MAYBE_USED:
                    age = ages.get((row, col, kind))
                    if age is None:
                        self.events.append(f"wave {wave}: {kind} at row {row} col {col} is gone "
                                           f"(exploded, or eaten before it armed){zs}")
                    elif age < POTATO_MINE_ARM_SECONDS:
                        self.unarmed_mines += 1
                        self.events.append(f"wave {wave}: {kind} at row {row} col {col} was eaten "
                                           f"{age:.0f}s after planting, before it armed{zs}")
                    else:
                        self.used_count[kind] = self.used_count.get(kind, 0) + 1
                        self.events.append(f"wave {wave}: {kind} at row {row} col {col} exploded "
                                           f"({age:.0f}s after planting){zs}")
                else:
                    self.lost_count[kind] = self.lost_count.get(kind, 0) + 1
                    self.events.append(f"wave {wave}: lost {kind} at row {row} col {col}{zs}")
            for row, (old, new) in enumerate(zip(self.last.get("mowers", []), state.get("mowers", []))):
                if old and not new:
                    self.mower_wave[row] = wave
                    attackers = sum(1 for p in self.last["plants"] if p["row"] == row and p["type"] in SHOOTERS)
                    self.events.append(f"wave {wave}: the lawn mower in row {row} fired; that row had "
                                       f"{attackers} attackers and now has no mower")
        for p in state["plants"]:
            self.planted.setdefault(p["type"], set()).add((p["row"], p["col"]))
        self.last = state

    def ending(self):
        """Which row the zombies broke through, from the last board seen."""
        if not self.last or not self.last.get("zombies"):
            return None
        z = min(self.last["zombies"], key=lambda z: z["x"])
        row = z["row"]
        attackers = sum(1 for p in self.last["plants"] if p["row"] == row and p["type"] in SHOOTERS)
        mower = (f"its mower had fired in wave {self.mower_wave[row]}" if row in self.mower_wave
                 else "its mower had already been used" if not self.last["mowers"][row] else "it still had a mower")
        return (f"How it ended: the zombie closest to the house was a {z['type']} in row {row}; "
                f"{mower}, and the row had {attackers} attackers left.")

    def report(self, final_board_text=None, outcome=None):
        lines = []
        if self.loadout:
            lines.append("Loadout: " + ", ".join(self.loadout))
        left_out = [n for n in self.options if n not in self.loadout]
        if left_out:
            lines.append("Plants you could have brought but didn't: " + ", ".join(left_out))
        if self.last:
            w = self.last.get("wave", [0, 0])
            lines.append(f"Reached wave {w[0]} of {w[1]}. Mowers left: {sum(self.last.get('mowers', []))}.")
        if self.unarmed_mines:
            lines.append(f"Potato mines eaten before they armed: {self.unarmed_mines}")
        if self.lost_count:
            lines.append("Plants destroyed by zombies: " + ", ".join(f"{k} x{v}" for k, v in self.lost_count.items()))
        if self.used_count:
            lines.append("One-use plants used: " + ", ".join(f"{k} x{v}" for k, v in self.used_count.items()))
        lines.append("Timeline:")
        lines += [f"  {e}" for e in self.events[-40:]] or ["  (no plants lost, no mowers used)"]
        if outcome == "lost" and (end := self.ending()):
            lines += ["", end]
        if final_board_text:
            lines += ["", "Last board you saw:", final_board_text]
        return "\n".join(lines)
