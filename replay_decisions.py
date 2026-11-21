"""Replay recorded boards through today's observations; optional cheap player calls, never clicks."""
import argparse
import copy
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from placement import legal_targets, validate


def recorded_cases(path, numbers):
    records = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    for number in numbers:
        index = next(i for i, r in enumerate(records) if r["kind"] == "decision" and r["n"] == number)
        row = records[index]
        prior = records[:index]
        start = next(r for r in reversed(prior) if r["kind"] == "level_start")
        pick = next((r for r in reversed(prior) if r["kind"] == "seed_pick"), {})
        prompt = row.get("prompt") or ""
        # Current decision queue edits are logged BEFORE its decision record.
        # Only the queue in the observed prompt existed when the request began.
        pending = []
        for line in prompt.splitlines():
            if not line.strip().startswith("#"):
                continue
            match = re.fullmatch(r"\s+#(\d+) (plant (\w+)|shovel|break_vase) at "
                                 r"\((\d+),(\d+)\), (ordered|independent)(?:, group (\d+))?", line)
            if not match:
                raise ValueError(f"Unrecognized recorded queue line: {line}")
            ident, move, name, row, col, policy, group = match.groups()
            item = {"type": "plant" if name else move, "row": int(row), "col": int(col), "id": int(ident)}
            if name:
                item["seed"] = name
            if policy == "independent":
                item["independent"] = True
            if group:
                item["group"] = int(group)
            pending.append(item)
        yield {"number": number, "row": row, "start": start, "pick": pick,
               "queue": pending, "original_prompt": prompt}


def historical_notes(journal_path, cutoff, level):
    """No future reflections and no writes to the real notebook."""
    from journal import Journal, situation_of
    journal = Journal(Path(journal_path).parent)
    journal.data = copy.deepcopy(json.loads(Path(journal_path).read_text(encoding="utf-8")))
    history = [h for h in journal.data.get("history", []) if h.get("t", "") < cutoff]
    journal.data["history"] = history
    previous = history[-1] if history else {}
    journal.data["lessons"] = previous.get("lessons", [])
    journal.data["sections"] = {}
    for h in history:
        if h.get("situation"):
            journal.data["sections"][h["situation"]] = h.get("situation_lessons", [])
    label = f"{(level['level'] - 1) // 10 + 1}-{(level['level'] - 1) % 10 + 1}"
    return journal.prompt_block(situation_of(level), label)


def replay(path, numbers, player=False, journal_path="journal/lessons.json"):
    import brains
    from check_player_contract import validate_schema
    brain = None
    results = []
    try:
        if player:
            os.environ.update(PVZ_MODEL="haiku", PVZ_EFFORT="low", PVZ_PLAN_EFFORT="low")
            brain = brains.make_brain("subscription")
        for case in recorded_cases(path, numbers):
            original = case["row"]
            state = copy.deepcopy(original["state"])
            before = copy.deepcopy(state)
            names = [s["name"] for s in state["seeds"] if not s["name"].startswith("unknown")]
            schema = brains.decision_schema(names)
            # Preserve recent factual feedback from the recorded prompt; no operator hint.
            old_prompt = case["original_prompt"]
            marker = "Results of your recent actions, and things that happened:"
            recent = old_prompt.split(marker, 1)[1].strip().splitlines() if marker in old_prompt else []
            prompt = brains.describe(state, recent, case["queue"], names, compact=True)
            result = {"decision": original["n"], "original_decision": original["decision"],
                      "legal_targets": legal_targets(state), "prompt": prompt,
                      "original_think_seconds": original["think_seconds"]}
            if brain:
                brain.plan = case["pick"].get("plan")
                brain.level = state["level"]
                brain.set_loadout(names, state["level"])
                brain.notes = historical_notes(journal_path, case["start"]["t"], case["start"])
                started = datetime.now()
                answer = brain.ask(brain.system(brains.SYSTEM_PROMPT), prompt, schema)
                validate_schema(answer, schema)
                result.update(answer=answer, usage=brain.last_usage,
                              model="haiku", effort="low",
                              seconds=round((datetime.now() - started).total_seconds(), 2),
                              action_validation=[{"action": a, "status": validate(a, state)[0],
                                                  "reason": validate(a, state)[1]} for a in answer["actions"]])
            if state != before:
                raise AssertionError("Read-only replay mutated its board")
            results.append(result)
    finally:
        if brain:
            brain.close()
    return {"source": str(path), "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "mode": "offline player, no clicks" if player else "observations only, no player calls or clicks",
            "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--decisions", type=int, nargs="+", default=[84, 107, 108])
    parser.add_argument("--player", action="store_true", help="make one Haiku/low call per recorded board")
    parser.add_argument("--journal", type=Path, default=Path("journal/lessons.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.log, args.decisions, args.player, args.journal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for case in result["cases"]:
        print(json.dumps({k: v for k, v in case.items() if k not in ("prompt", "usage", "legal_targets")}, ensure_ascii=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
