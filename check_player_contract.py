"""One cheap player call on a recorded board, with no game reads or clicks."""
import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def validate_schema(value, schema):
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["execution-tracking", "queue-editing", "reflection"])
    args = ap.parse_args()
    os.environ["PVZ_MODEL"] = "haiku"
    os.environ["PVZ_EFFORT"] = "low"
    os.environ["PVZ_PLAN_EFFORT"] = "low"
    from brains import make_brain
    path = Path("snapshots/2026-11-20_before_execution_learning")
    records = [json.loads(l) for l in Path("logs/run_2026-11-20_12-40-32_subscription.jsonl").read_text(encoding="utf-8").splitlines()]
    original = next(r for r in records if r["kind"] == "decision" and r["n"] == 3)
    brain = make_brain("subscription")
    brain.level = original["state"]["level"]
    brain.set_loadout([s["name"] for s in original["state"]["seeds"]], brain.level)
    brain.plan = next(r["plan"] for r in records if r["kind"] == "seed_pick")
    # Read a frozen notebook directly; do not seed sections or save anything back.
    notebook = json.loads((path / "journal_haiku_from_sonnet/lessons.json").read_text(encoding="utf-8"))
    brain.notes = "\n\nYour journal:\n" + "\n".join(notebook.get("lessons", []) + notebook.get("sections", {}).get("fog", []))
    queue = [{"id": 1, "type": "plant", "seed": "sunflower", "row": 5, "col": 0},
             {"id": 2, "type": "plant", "seed": "fume_shroom", "row": 1, "col": 1}]
    started = time.monotonic()
    try:
        if args.stage == "reflection":
            from journal import Journal, REFLECT_SCHEMA
            sample = next(r for r in records if r["kind"] == "journal")
            source = records[:records.index(sample)]
            evidence = {f"r{i + 1}": r for i, r in enumerate(source)
                        if r["kind"] in ("action", "event", "level_end")}
            report = sample["report"] + "\n\nRecorded event references:\n" + "\n".join(
                f"[{key}] {r.get('result', r.get('text', r.get('outcome')))}" for key, r in evidence.items())
            journal = Journal(Path("research") / ("contract_reflection_" + datetime.now().strftime("%H%M%S")))
            journal.data = notebook
            captured = []
            real_ask = brain.ask
            def checked_ask(*a, **kw):
                answer = real_ask(*a, **kw)
                captured.append(answer)
                validate_schema(answer, REFLECT_SCHEMA)
                return answer
            brain.ask = checked_ask
            journal.reflect(brain, "4-1", "lost", report, "fog", brain.plan,
                            attempt="recorded-4-1-attempt1", evidence=evidence)
            public = captured[0]
            result = {"stage": args.stage, "kind": "contract_check", "model": brain.model,
                      "effort": brain.effort, "usage": brain.last_usage, "answer": public,
                      "seconds": round(time.monotonic() - started, 2), "t": datetime.now().isoformat()}
            with Path("logs/player_contract_checks.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
            print(json.dumps(result))
            return
        import brains as protocol
        if args.stage == "execution-tracking":
            import importlib.util
            spec = importlib.util.spec_from_file_location("tracking_protocol", path / "brains.py")
            protocol = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(protocol)
        prompt = protocol.describe(original["state"], [], queue, brain.known_plants, compact=True)
        completed = Counter(r["action"].get("seed") for r in records[:records.index(original)]
                            if r["kind"] == "action" and r["result"].startswith("OK"))
        prompt += "\nRecorded execution: completed plants by seed: " + json.dumps(completed)
        prompt += ". Historical action IDs and wait durations are unavailable."
        answer = brain.ask(brain.system(protocol.SYSTEM_PROMPT), prompt, protocol.DECISION_SCHEMA)
        public = {k: v for k, v in answer.items() if not k.startswith("_")}
        validate_schema(public, protocol.DECISION_SCHEMA)
        if args.stage != "execution-tracking":
            from queueing import edit_queue
            from execution import ExecutionTracker
            tracker = ExecutionTracker("recorded-board-contract", lambda **r: None)
            tracked = [tracker.issue(a, 0) for a in queue]
            edit_queue(tracked, public, tracker, 1, original["state"])
        result = {"stage": args.stage, "kind": "contract_check", "model": brain.model,
                  "effort": brain.effort, "usage": brain.last_usage, "answer": public,
                  "seconds": round(time.monotonic() - started, 2), "t": datetime.now().isoformat()}
        with Path("logs/player_contract_checks.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
        print(json.dumps(result))
    except Exception as error:
        failure = {"kind": "contract_check_error", "stage": args.stage, "model": brain.model,
                   "effort": brain.effort, "error": str(error), "usage": brain.last_usage,
                   "t": datetime.now().isoformat()}
        with Path("logs/player_contract_checks.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(failure) + "\n")
        raise
    finally:
        brain.close()


if __name__ == "__main__":
    main()
