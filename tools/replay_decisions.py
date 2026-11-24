"""Replay recorded boards through today's observations; optional cheap player calls, never clicks."""
import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import types
from datetime import datetime, timedelta
from pathlib import Path

from pvz.player.placement import legal_targets, validate


def fresh_recorded_feedback(records, index, start, fresh_only=True):
    """Approximate old request timestamps; new logs carry their exact captured batch."""
    from pvz.player.brains import action_text
    current = records[index]
    if fresh_only and isinstance(current.get("feedback"), list) and all(
        isinstance(e, dict) for e in current["feedback"]
    ):
        return current["feedback"], current["state"].get("feedback_omitted", 0), "recorded batch"
    def request_at(row):
        if row.get("state", {}).get("observed_at"):
            return datetime.fromisoformat(row["state"]["observed_at"])
        return datetime.fromisoformat(row["t"]) - timedelta(seconds=row.get("think_seconds", 0))
    cutoff = request_at(current)
    rejected = {r.get("decision") for r in records[start:index]
                if r["kind"] == "execution_event" and r.get("event") == "queue_edit_rejected"}
    previous = next((r for r in reversed(records[start:index]) if r["kind"] == "decision"
                     and r["n"] not in rejected and "brain error:" not in r.get("decision", {}).get("reasoning", "")), None)
    acknowledged = request_at(previous) if previous and fresh_only else datetime.fromisoformat(records[start]["t"])
    events = []
    for n, row in enumerate(records[start:index], start):
        when = datetime.fromisoformat(row["t"])
        if not acknowledged < when <= cutoff:
            continue
        if row["kind"] == "event":
            text = "EVENT: " + row["text"]
        elif row["kind"] == "action":
            result = row["result"]
            status = result.split(" ", 1)[0]
            text = f"{status} {action_text(row['action'])}"
            if status == "SKIPPED":
                text += ": " + result.rsplit("}: ", 1)[-1]
            elif status == "FAILED":
                text += ": click did not register"
        else:
            continue
        events.append({"id": n, "text": text, "age_seconds": round((cutoff - when).total_seconds(), 1),
                       "approximate_age": True})
    return events[-8:], max(0, len(events) - 8), "reconstructed; request times estimated from logged durations"


def baseline_module(revision):
    """Load only the requested tracked formatter; never replace the working tree."""
    commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], text=True).strip()
    for path in ("pvz/player/brains.py", "brains.py"):     # brains.py was at the top level before Nov 25
        try:
            source = subprocess.check_output(["git", "show", f"{commit}:{path}"], text=True, encoding="utf-8",
                                             stderr=subprocess.DEVNULL)
            break
        except subprocess.CalledProcessError:
            continue
    else:
        raise SystemExit(f"no brains.py at {commit}")
    if path == "brains.py":
        # Old top-level imports (`import offsets`, `from placement import ...`) resolve to today's modules.
        import sys
        for pkg in ("pvz.game", "pvz.player"):
            folder = str(Path(__file__).resolve().parents[1] / pkg.replace(".", "/"))
            if folder not in sys.path:
                sys.path.append(folder)
    module = types.ModuleType("replay_baseline_brains")
    exec(compile(source, f"git:{commit}:{path}", "exec"), module.__dict__)
    return module, commit


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
            ident, move, name, queue_row, queue_col, policy, group = match.groups()
            item = {"type": "plant" if name else move, "row": int(queue_row), "col": int(queue_col), "id": int(ident)}
            if name:
                item["seed"] = name
            if policy == "independent":
                item["independent"] = True
            if group:
                item["group"] = int(group)
            pending.append(item)
        yield {"number": number, "row": row, "start": start, "pick": pick,
               "queue": pending, "original_prompt": prompt,
               "fresh_feedback": fresh_recorded_feedback(records, index, records.index(start)),
               "legacy_feedback": fresh_recorded_feedback(records, index, records.index(start), fresh_only=False)[0]}


def historical_notes(journal_path, cutoff, level):
    """No future reflections and no writes to the real notebook."""
    from pvz.player.journal import Journal, situation_of
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


def replay(path, numbers, player=False, journal_path="journal/lessons.json", compare_to=None):
    from pvz.player import brains
    from pvz.player.action_contract import validate_schema
    brain = None
    results = []
    baseline, baseline_commit = baseline_module(compare_to) if compare_to else (None, None)
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
            fresh, omitted, provenance = case["fresh_feedback"]
            state["feedback_omitted"] = omitted
            prompt = brains.describe(state, fresh, case["queue"], names, compact=True)
            result = {"decision": original["n"], "original_decision": original["decision"],
                      "legal_targets": legal_targets(state), "prompt": prompt,
                      "feedback": fresh, "feedback_provenance": provenance,
                      "prompt_chars": len(prompt),
                      "original_think_seconds": original["think_seconds"]}
            if baseline:
                baseline_recent = recent if marker in old_prompt else [e["text"] for e in case["legacy_feedback"]]
                base_prompt = baseline.describe(state, baseline_recent, case["queue"], names, compact=True)
                result.update(baseline_prompt=base_prompt, baseline_prompt_chars=len(base_prompt),
                              chars_saved=len(base_prompt) - len(prompt))
            if brain:
                brain.plan = case["pick"].get("plan")
                brain.level = state["level"]
                brain.set_loadout(names, state["level"])
                brain.notes = historical_notes(journal_path, case["start"]["t"], case["start"])
                if baseline:
                    started = datetime.now()
                    base_answer = brain.ask(brain.system(baseline.SYSTEM_PROMPT), base_prompt, schema)
                    validate_schema(base_answer, schema)
                    result.update(baseline_answer=base_answer, baseline_usage=brain.last_usage,
                                  baseline_seconds=round((datetime.now() - started).total_seconds(), 2),
                                  baseline_action_validation=[{"action": a, "status": validate(a, state)[0],
                                                               "reason": validate(a, state)[1]} for a in base_answer["actions"]])
                started = datetime.now()
                answer = brain.ask(brain.system(brains.SYSTEM_PROMPT), prompt, schema)
                validate_schema(answer, schema)
                result.update(answer=answer, usage=brain.last_usage,
                              model="haiku", effort="low",
                              seconds=round((datetime.now() - started).total_seconds(), 2),
                              action_validation=[{"action": a, "status": validate(a, state)[0],
                                                  "reason": validate(a, state)[1]} for a in answer["actions"]])
            # Feedback metadata is supplied for formatting; gameplay fields stay untouched.
            before["feedback_omitted"] = omitted
            if state != before:
                raise AssertionError("Read-only replay mutated its board")
            results.append(result)
    finally:
        if brain:
            brain.close()
    return {"source": str(path), "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "baseline_commit": baseline_commit,
            "mode": "offline player, no clicks" if player else "observations only, no player calls or clicks",
            "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--decisions", type=int, nargs="+", default=[84, 107, 108])
    parser.add_argument("--player", action="store_true", help="make one Haiku/low call per recorded board")
    parser.add_argument("--compare-to", help="compare with brains.py at a checkpoint; --player calls each version")
    parser.add_argument("--journal", type=Path, default=Path("journal/lessons.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.log, args.decisions, args.player, args.journal, args.compare_to)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for case in result["cases"]:
        print(json.dumps({k: v for k, v in case.items() if k not in (
            "prompt", "baseline_prompt", "usage", "baseline_usage", "legal_targets", "feedback")}, ensure_ascii=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
