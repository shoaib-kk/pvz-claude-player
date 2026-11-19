"""The player's own lessons journal.

After every finished level the player looks back at what happened (a factual
timeline the agent records: loadout, plants lost, mowers used, final board) and
rewrites its list of lessons in its own words. The journal carries across levels and
runs, and goes into the player's prompts, so strategy is learned rather than
hard-coded. It lives in journal/ (git-ignored); journal/lessons.md is a readable copy
for the video.
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_LESSONS = 12

REFLECT_SYSTEM = """You are the player in a run of Plants vs. Zombies, reviewing a level you just finished.
You keep a short journal of lessons that you will read before every future level.
Look at what happened and rewrite the whole journal: keep lessons that still hold, fix or
merge ones this level proved wrong or incomplete, and add what you learned now.
Lessons must be concrete and in your own words (plant placement, timing, economy,
specific zombies), about things you control: which plants you bring, and what you plant or
shovel where and when. Lawn mowers fire by themselves; plants can't be moved. At most %d lessons, one or two sentences each, most important first.
Also write a one-sentence summary of why you won or lost this level.
Answer with JSON only.""" % MAX_LESSONS

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "lessons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "lessons"],
    "additionalProperties": False,
}


class Journal:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else ROOT / "journal"
        self.path = self.folder / "lessons.json"
        self.data = {"lessons": [], "history": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    @property
    def lessons(self):
        return list(self.data.get("lessons", []))

    def prompt_block(self):
        """Text appended to the player's system prompts."""
        if not self.lessons:
            return ("\n\nYour journal is empty: you haven't finished a level yet. "
                    "Work out what works by playing.")
        return ("\n\nYour journal - lessons you wrote yourself after earlier levels:\n"
                + "\n".join(f"- {x}" for x in self.lessons))

    def reflect(self, brain, level_label, outcome, report):
        """Ask the player to rewrite its journal. Returns the summary, or None."""
        ask = getattr(brain, "ask", None)
        if not ask:
            return None
        current = "\n".join(f"- {x}" for x in self.lessons) or "(empty)"
        prompt = (f"Level {level_label}: you {outcome.upper()}.\n\n{report}\n\n"
                  f"Your journal before this level:\n{current}")
        answer = ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA)
        lessons = [str(x).strip() for x in answer.get("lessons", []) if str(x).strip()][:MAX_LESSONS]
        summary = str(answer.get("summary", "")).strip()
        self.data["lessons"] = lessons
        self.data.setdefault("history", []).append({
            "level": level_label, "outcome": outcome, "summary": summary, "lessons": lessons,
            "t": datetime.now().isoformat(timespec="seconds"),
        })
        self.save()
        return summary

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        md = ["# Claude's PvZ journal", "", "## Current lessons", ""]
        md += [f"{i}. {x}" for i, x in enumerate(self.lessons, 1)] or ["(none yet)"]
        md += ["", "## Level history", ""]
        for h in self.data.get("history", []):
            md.append(f"- **{h['level']}** ({h['outcome']}, {h['t']}): {h['summary']}")
        (self.folder / "lessons.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# Plants that disappear when they do their job, so disappearing isn't a loss.
ONE_USE = {"cherry_bomb", "jalapeno", "squash", "ice_shroom", "doom_shroom", "grave_buster",
           "coffee_bean", "blover", "tangle_kelp", "hypno_shroom", "explode_o_nut"}
MAYBE_USED = {"potato_mine"}     # exploded, or eaten while still arming - indistinguishable here


class LevelRecorder:
    """Factual timeline of one level, built from the boards sent to the player."""

    def __init__(self, level_label, loadout=None):
        self.level_label = level_label
        self.loadout = list(loadout or [])
        self.events = []
        self.last = None
        self.lost_count = {}
        self.used_count = {}
        self.planted = {}

    def observe(self, state):
        if not state or not state.get("in_level"):
            return
        wave = state.get("wave", [0, 0])[0]
        if self.last is not None:
            before = {(p["row"], p["col"], p["type"]) for p in self.last["plants"]}
            after = {(p["row"], p["col"], p["type"]) for p in state["plants"]}
            for row, col, kind in sorted(before - after):
                near = [z["type"] for z in state["zombies"] if z["row"] == row]
                zs = f" (zombies in that row: {', '.join(sorted(set(near)))})" if near else ""
                if kind in ONE_USE:
                    self.used_count[kind] = self.used_count.get(kind, 0) + 1
                    self.events.append(f"wave {wave}: {kind} at row {row} col {col} was used up{zs}")
                elif kind in MAYBE_USED:
                    self.events.append(f"wave {wave}: {kind} at row {row} col {col} is gone "
                                       f"(exploded, or eaten before it armed){zs}")
                else:
                    self.lost_count[kind] = self.lost_count.get(kind, 0) + 1
                    self.events.append(f"wave {wave}: lost {kind} at row {row} col {col}{zs}")
            for row, (old, new) in enumerate(zip(self.last.get("mowers", []), state.get("mowers", []))):
                if old and not new:
                    self.events.append(f"wave {wave}: lawn mower used in row {row}")
        for p in state["plants"]:
            self.planted.setdefault(p["type"], set()).add((p["row"], p["col"]))
        self.last = state

    def report(self, final_board_text=None):
        lines = []
        if self.loadout:
            lines.append("Loadout: " + ", ".join(self.loadout))
        if self.last:
            w = self.last.get("wave", [0, 0])
            lines.append(f"Reached wave {w[0]} of {w[1]}. Mowers left: {sum(self.last.get('mowers', []))}.")
        if self.lost_count:
            lines.append("Plants destroyed by zombies: " + ", ".join(f"{k} x{v}" for k, v in self.lost_count.items()))
        if self.used_count:
            lines.append("One-use plants used: " + ", ".join(f"{k} x{v}" for k, v in self.used_count.items()))
        lines.append("Timeline:")
        lines += [f"  {e}" for e in self.events[-40:]] or ["  (no plants lost, no mowers used)"]
        if final_board_text:
            lines += ["", "Last board you saw:", final_board_text]
        return "\n".join(lines)
