"""The player's own lessons journal.

After every finished level the player looks back at what happened (a factual
timeline the agent records: loadout, its own pre-level plan, plants lost, mowers used,
final board) and rewrites its lessons in its own words. Lessons are kept in two parts:
general ones, and ones for the current situation (night, pool, conveyor...), so that
lessons for one kind of level don't crowd out another's. The journal carries across
levels and runs and goes into the player's prompts, so strategy is learned rather than
hard-coded. It lives in journal/ (git-ignored); journal/lessons.md is a readable copy.
"""
import json
from datetime import datetime
from pathlib import Path

from plant_info import POTATO_MINE_ARM_SECONDS
from sun_accounting import MECHANICS_AND_EVIDENCE, verified_costs
from purchase_accounting import PurchaseLedger
from plan_progress import PlanProgress

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
Separate observed facts (with event IDs) from your hypothesis and your next attempt's experiment.
Assess whether your previous experiment and written plan were actually executed before judging
whether they worked. Distinguish requested moves from completed moves; waiting and cancellation
are execution outcomes. A fact about this attempt is not automatically a rule about all levels.
For each new or changed lesson, give its scope, 1-based index, and supporting event IDs in
lesson_evidence. References support observations, not proof of a hypothesis. Prior lessons without
recorded evidence are unverified; you may retain, revise, or remove them yourself. Keep evidence
out of the lesson sentences. Use current event IDs for new evidence; unchanged lessons retain
their earlier provenance automatically. Keep observed to at most 4 items; hypothesis, next_attempt, and
plan_assessment are each one short sentence. Choose the experiment yourself.
Answer with JSON only.""" % (MAX_LESSONS, MAX_SITUATION)
REFLECT_SYSTEM += MECHANICS_AND_EVIDENCE

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "general_lessons": {"type": "array", "items": {"type": "string"}},
        "situation_lessons": {"type": "array", "items": {"type": "string"}},
        "observed": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "properties": {
                "fact": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            }, "required": ["fact", "evidence"], "additionalProperties": False}},
        "hypothesis": {"type": "string"},
        "next_attempt": {"type": "string"},
        "plan_assessment": {"type": "string"},
        "lesson_evidence": {"type": "array", "maxItems": MAX_LESSONS + MAX_SITUATION, "items": {
            "type": "object", "properties": {
                "scope": {"type": "string", "enum": ["general", "situation"]},
                "index": {"type": "integer", "minimum": 1},
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            }, "required": ["scope", "index", "evidence"], "additionalProperties": False}},
    },
    "required": ["summary", "general_lessons", "situation_lessons", "observed", "hypothesis",
                 "next_attempt", "plan_assessment", "lesson_evidence"],
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
        seeded = self.data.get("seeded", [])
        if not parent or situation in seeded or not self.section(parent):
            return
        merged = list(dict.fromkeys(self.section(parent) + self.section(situation)))[:MAX_SITUATION]
        self.data["sections"][situation] = merged
        self.data.setdefault("seeded", []).append(situation)
        self.save()

    def prompt_block(self, situation=None, level_label=None):
        """Text appended to the player's system prompts."""
        self.seed_section(situation)
        general, special = self.lessons, self.section(situation)
        text = ("\n\nYour journal is empty for this: you haven't finished a level like it yet. "
                "Work out what works by playing." if not general and not special else
                "\n\nYour journal - strategy hypotheses you wrote after earlier levels "
                "(revisable; current costs and mechanics take precedence):")
        if general:
            text += "\nGeneral:\n" + "\n".join(f"- {x}" for x in general)
        if situation:
            text += f"\nFor {situation} levels:\n" + ("\n".join(f"- {x}" for x in special)
                                                      if special else "- (none yet)")
        previous = next((h for h in reversed(self.data.get("history", []))
                         if h.get("situation") == situation and h.get("next_attempt")), None)
        if previous:
            text += "\nYour experiment for the next attempt: " + previous["next_attempt"]
        if level_label:
            text += self.selection_history(level_label)
        return text

    def selection_history(self, level_label):
        """Keep the furthest recorded result plus recent results visible before a pick."""
        history = [h for h in self.data.get("history", []) if h.get("level") == level_label]
        if not history:
            return ""
        def score(h):
            facts = h.get("attempt_facts") or facts_from_evidence(h.get("evidence")) or {}
            return h.get("outcome") == "won", (facts.get("wave") or [0])[0]
        best = max(range(len(history)), key=lambda i: score(history[i]))
        chosen = sorted({best, *range(max(0, len(history) - 2), len(history))})
        lines = [f"\nRecorded outcomes at level {level_label} (observations, not proven strategies; "
                 "starting conditions and other choices can differ):"]
        for index in chosen:
            h = history[index]
            f = h.get("attempt_facts") or facts_from_evidence(h.get("evidence")) or {}
            w = f.get("wave") or [0, 0]
            counts = f.get("planted") or ((h.get("evidence") or {}).get("s0") or {}).get("planted")
            accounting = f.get("accounting") or {}
            mowers = accounting.get("initial_mowers")
            lines.append(f"  {h.get('t', '?')}: {h.get('outcome', '?')} wave {w[0]}/{w[1]}; "
                         f"loadout {', '.join(f.get('loadout', [])) or 'not recorded'}; "
                         f"completed plantings {counts if counts is not None else 'not recorded'}; "
                         f"starting cleaners {sum(mowers) if mowers is not None else 'not recorded'}.")
        return "\n".join(lines)

    def earlier_attempts(self, level_label, limit=12):
        """One factual line per earlier finished attempt at this level, oldest first."""
        lines = []
        for h in [h for h in self.data.get("history", []) if h.get("level") == level_label][-limit:]:
            f = h.get("attempt_facts") or facts_from_evidence(h.get("evidence"))
            if not f:
                lines.append(f"  - {h.get('t', '?')}: {h.get('outcome', '?')} (no facts recorded)")
                continue
            wave = f.get("wave") or [0, 0]
            parts = [f"{h.get('t', '?')}: {h.get('outcome', '?')} at wave {wave[0]} of {wave[1]}"]
            if f.get("loadout"):
                parts.append("loadout " + ", ".join(f["loadout"]))
            if f.get("plants_placed") is not None:
                parts.append(f"plants placed {f['plants_placed']}")
            replacement = f.get("replacement_value_disappeared", f.get("sun_lost"))
            if replacement is not None:
                parts.append(f"replacement value of disappeared plants {replacement} (not spending)")
            if f.get("accounting"):
                parts.append(f"packet spending {f['accounting']['packet_sun_spent']}")
            if f.get("stalled_unspent_sun_seconds") is not None:
                parts.append(f"queue stalled with unspent sun {f['stalled_unspent_sun_seconds']:.0f}s")
            lines.append("  - " + "; ".join(parts))
        return lines

    def reflect(self, brain, level_label, outcome, report, situation=None, plan=None,
                attempt=None, evidence=None, facts=None):
        """Ask the player to rewrite its journal. Returns the summary, or None."""
        ask = getattr(brain, "ask", None)
        if not ask:
            return None
        general = "\n".join(f"- {x}" for x in self.lessons) or "(empty)"
        special = "\n".join(f"- {x}" for x in self.section(situation)) or "(empty)"
        previous = next((h for h in reversed(self.data.get("history", []))
                         if h.get("situation") == situation), {})
        evidence = evidence or {}
        board = evidence.get("b0")
        if not isinstance(board, dict):
            board = None
        costs = verified_costs(board)
        earlier = self.earlier_attempts(level_label)
        this = dict(facts or facts_from_evidence(evidence) or {})
        prompt = (f"Level {level_label} ({situation or 'unknown'} situation): you {outcome.upper()}.\n\n"
                  + f"Attempt: {attempt or 'legacy'}; valid current event IDs: {', '.join(evidence)}.\n"
                  + f"Your previous experiment: {previous.get('next_attempt', '(none recorded)')}\n"
                  + "Verified packet sun costs (null means unknown; supports are separate):\n"
                  + json.dumps(costs, ensure_ascii=False) + "\n"
                  + "Check every retained or revised sun-spending claim against these costs. "
                    "Distinguish packet spending, support spending, space/recharge/slot tradeoffs, "
                    "and observed contributions. A plant's death alone does not measure its "
                    "damage or time bought; do not infer zero contribution from disappearance.\n"
                  + (f"The plan you wrote before the level:\n{plan}\n\n" if plan else "")
                  + ("Your earlier attempts at this level (recorded facts, oldest first):\n"
                     + "\n".join(earlier) + "\n\n" if earlier else "")
                  + f"{report}\n\nYour journal before this level:\nGeneral:\n{general}\n"
                  f"For {situation or 'this kind of'} levels:\n{special}\n"
                  + "Prior lesson evidence (unlisted lessons have no recorded provenance):\n"
                  + json.dumps(previous.get("lesson_evidence", []), ensure_ascii=False))
        effort = getattr(brain, "plan_effort", None)
        answer = (ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA, effort=effort) if effort
                  else ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA))
        lessons = _clean(answer.get("general_lessons", answer.get("lessons")), MAX_LESSONS)
        situation_lessons = _clean(answer.get("situation_lessons"), MAX_SITUATION)
        summary = str(answer.get("summary", "")).strip()
        def references(refs):
            return [r for r in refs if isinstance(r, str) and r in evidence][:4]
        observed = [{"fact": str(o.get("fact", "")), "evidence": references(o.get("evidence", []))}
                    for o in answer.get("observed", [])[:4] if isinstance(o, dict)]
        links = []
        for item in answer.get("lesson_evidence", []):
            scope, index = item.get("scope"), item.get("index")
            items = lessons if scope == "general" else situation_lessons if scope == "situation" else []
            if type(index) is int and 1 <= index <= len(items):
                refs = references(item.get("evidence", []))
                links.append({"scope": scope, "index": index, "lesson": items[index - 1],
                              "attempt": attempt, "evidence": refs})
        inherited = {(link.get("scope"), link.get("lesson")): link
                     for h in self.data.get("history", []) if h.get("situation") == situation
                     for link in h.get("lesson_evidence", []) if link.get("evidence")}
        linked = {(link["scope"], link["index"]) for link in links if link["evidence"]}
        for scope, items in (("general", lessons), ("situation", situation_lessons)):
            for index, lesson in enumerate(items, 1):
                if (scope, index) not in linked and (scope, lesson) in inherited:
                    links.append({**inherited[scope, lesson], "index": index})
        self.data["lessons"] = lessons
        if situation:
            self.data["sections"][situation] = situation_lessons
        self.data.setdefault("history", []).append({
            "level": level_label, "outcome": outcome, "situation": situation, "summary": summary,
            "plan": plan, "lessons": lessons, "situation_lessons": situation_lessons,
            "attempt": attempt, "observed": observed,
            "hypothesis": str(answer.get("hypothesis", "")),
            "next_attempt": str(answer.get("next_attempt", "")),
            "plan_assessment": str(answer.get("plan_assessment", "")),
            "lesson_evidence": links, "evidence": evidence,
            "verified_packet_costs": costs, "attempt_facts": this or None,
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
            for field in ("plan_assessment", "hypothesis", "next_attempt"):
                if h.get(field):
                    md.append(f"  - {field.replace('_', ' ').capitalize()}: {h[field]}")
        (self.folder / "lessons.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def facts_from_evidence(evidence):
    """Attempt facts rebuilt from a stored reflection's evidence (final board, execution metrics)."""
    board = (evidence or {}).get("b0")
    if not isinstance(board, dict) or "wave" not in board:
        return None
    metrics = (evidence or {}).get("s0") or {}
    planted = metrics.get("planted")
    return {"loadout": [s["name"] for s in board.get("seeds", [])], "wave": list(board["wave"]),
            "plants_placed": sum(planted.values()) if isinstance(planted, dict) else None,
            "stalled_unspent_sun_seconds": metrics.get("queue_stalled_unspent_sun_seconds")}


# These can disappear after activation or after being destroyed. Snapshots alone
# cannot establish which happened, so neither a successful use nor a loss is counted.
ONE_USE = {"cherry_bomb", "jalapeno", "squash", "ice_shroom", "doom_shroom", "grave_buster",
           "coffee_bean", "blover", "tangle_kelp", "hypno_shroom", "explode_o_nut"}
MAYBE_USED = {"potato_mine"}     # exploded, or eaten while still arming - indistinguishable here


class LevelRecorder:
    """Factual timeline of one level, built from the boards sent to the player."""

    def __init__(self, level_label, loadout=None, options=None, objectives=None):
        self.level_label = level_label
        self.loadout = list(loadout or [])
        self.options = list(options or [])   # every plant the chooser offered
        self.events = []
        self.last = None
        self.lost_count = {}
        self.one_use_disappeared = {}
        self.used_count = {}
        self.unarmed_mines = 0
        self.mower_wave = {}
        self.planted = {}
        self.placed = 0           # plants that appeared on the lawn, replants included
        self.purchases = PurchaseLedger()
        self.progress = PlanProgress(objectives)

    def record_action(self, action, packet, before, after=None):
        """Called only for confirmed execution, not proposals or rejected orders."""
        if action["type"] == "plant":
            self.purchases.purchased(action, packet, before)
            self.progress.purchased(action, after if after is not None else before)
            if after is not None:
                self.purchases.observe(after)
        elif action["type"] == "shovel":
            self.purchases.shoveled(action, before, after)

    def costs(self):
        return verified_costs(self.last)

    def sun_lost(self):
        costs = self.costs()
        if any(costs.get(k) is None for k in self.lost_count):
            return None
        return sum(costs[k] * v for k, v in self.lost_count.items())

    def facts(self):
        """Comparable numbers for this attempt, kept in the journal history."""
        if not self.last:
            return None
        return {"loadout": self.loadout or [s["name"] for s in self.last.get("seeds", [])],
                "wave": list(self.last.get("wave", [0, 0])), "plants_placed": self.placed,
                "replacement_value_disappeared": self.purchases.metrics()["replacement_value_disappeared"],
                "accounting": self.purchases.metrics(),
                "objectives": self.progress.status(self.last)}

    def observe(self, state):
        if not state or not state.get("in_level"):
            return
        self.purchases.observe(state)
        wave = state.get("wave", [0, 0])[0]
        if self.last is not None:
            before = {(p["row"], p["col"], p["type"]) for p in self.last["plants"]}
            ages = {(p["row"], p["col"], p["type"]): p.get("age") for p in self.last["plants"]}
            after = {(p["row"], p["col"], p["type"]) for p in state["plants"]}
            for row, col, kind in sorted(before - after):
                near = [z["type"] for z in state["zombies"] if z["row"] == row]
                zs = f" (zombies in that row: {', '.join(sorted(set(near)))})" if near else ""
                if kind in ONE_USE:
                    self.one_use_disappeared[kind] = self.one_use_disappeared.get(kind, 0) + 1
                    self.events.append(f"wave {wave}: {kind} at row {row} col {col} is no longer observed "
                                       f"(activation or destruction unknown; effect unverified){zs}")
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
        seen = {(p["row"], p["col"], p["type"]) for p in self.last["plants"]} if self.last else set()
        self.placed += sum(1 for p in state["plants"] if (p["row"], p["col"], p["type"]) not in seen)
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
                 else "no mower was available (no firing observed)" if not self.last["mowers"][row] else "it still had a mower")
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
            costs = self.costs()
            def cost(k):
                return f"{costs[k]} sun each" if costs.get(k) is not None else "cost unknown"
            lines.append("Plants no longer observed (cause unverified): " + ", ".join(
                f"{k} x{v} ({cost(k)})" for k, v in self.lost_count.items()))
            if (lost := self.purchases.metrics()["replacement_value_disappeared"]) is not None:
                lines.append(f"Replacement value of disappeared plants: {lost} (NOT cash spent; includes free starting plants)")
        if self.used_count:
            lines.append("One-use plants used: " + ", ".join(f"{k} x{v}" for k, v in self.used_count.items()))
        if self.one_use_disappeared:
            lines.append("One-use plants no longer observed (activation or destruction unknown; effect unverified): "
                         + ", ".join(f"{k} x{v}" for k, v in self.one_use_disappeared.items()))
        lines.append("Timeline:")
        lines += [f"  [t{i + 1}] {e}" for i, e in list(enumerate(self.events))[-40:]] or ["  (no plants lost, no mowers used)"]
        if outcome == "lost" and (end := self.ending()):
            lines += ["", end]
        if self.purchases.initialized:
            lines += ["", "[a0] " + self.purchases.report()]
        progress = self.progress.report(self.last or {})
        if progress:
            lines += ["", "[p0] " + progress]
        if final_board_text:
            lines += ["", "Last board you saw:", final_board_text]
        return "\n".join(lines)
