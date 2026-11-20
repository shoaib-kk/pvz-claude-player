"""Read-only attempt metrics for old and instrumented JSONL logs. No player calls."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


def placement(a):
    return a.get("type"), a.get("seed"), a.get("row"), a.get("col")


def attempts(path, level=31):
    records = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, start in enumerate(records):
        if start["kind"] != "level_start" or start.get("level") != level:
            continue
        end = next((j for j in range(i + 1, len(records))
                    if records[j]["kind"] in ("level_end", "level_start", "stop")), len(records))
        rows = records[i:end + 1]
        ds = [r for r in rows if r["kind"] == "decision"]
        actions = [r for r in rows if r["kind"] == "action"]
        plants = [r for r in actions if r["result"].startswith("OK") and r["action"]["type"] == "plant"]
        proposed = [a for d in ds for a in d["decision"].get("actions", []) if a.get("type") == "plant"]
        requested = {placement(a) for a in proposed}
        confirmed = {placement(r["action"]) for r in plants}
        last = rows[-1]
        seconds = (datetime.fromisoformat(last["t"]) - datetime.fromisoformat(start["t"])).total_seconds()
        pick = next((r for r in reversed(records[:i]) if r["kind"] == "seed_pick"), {})
        reflection = next((r for r in records[end + 1:] if r["kind"] in ("journal", "level_start")), {})
        report = reflection.get("report", "") if reflection.get("kind") == "journal" else ""
        observed_blocked = 0
        sampled_seconds = 0.0
        # Old logs have decision snapshots, not tick-by-tick wait data. This is explicitly
        # a sample-and-hold estimate, never an exact measurement of historical wait time.
        from agent import validate
        for k, d in enumerate(ds):
            s, aa = d["state"], d["decision"].get("actions", [])
            if aa and s["sun"] > 0 and validate(aa[0], s)[0] == "later":
                observed_blocked += 1
                t = datetime.fromisoformat(d["t"]) - timedelta(seconds=d["think_seconds"])
                nxt = (datetime.fromisoformat(ds[k + 1]["t"]) - timedelta(seconds=ds[k + 1]["think_seconds"])) if k + 1 < len(ds) else t
                sampled_seconds += max(0, (nxt - t).total_seconds())
        tail_end = next((j for j in range(end + 1, len(records)) if records[j]["kind"] == "level_start"), len(records))
        summary = next((r for r in records[i:tail_end] if r["kind"] == "execution_summary"), {})
        yield {
            "file": str(path), "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "started": start["t"], "model": pick.get("model"), "outcome": last.get("outcome", "incomplete"),
            "duration_seconds": round(seconds, 1), "decisions": len(ds),
            "decisions_per_minute": round(60 * len(ds) / seconds, 2) if seconds else None,
            "plant_request_mentions": len(proposed), "unique_requested_placements": len(requested),
            "confirmed_plant_actions": len(plants), "unique_confirmed_requested_placements": len(requested & confirmed),
            "plants_by_seed": dict(Counter(r["action"].get("seed") for r in plants)),
            "deepest_decision_wave": max((d["state"]["wave"][0] for d in ds), default=None),
            "recorded_final_wave": next((l for l in report.splitlines() if l.startswith("Reached wave")), None),
            "blocked_with_unspent_sun_samples": observed_blocked,
            "blocked_with_unspent_sun_sample_hold_seconds": round(sampled_seconds, 1),
            "exact_execution_metrics": summary.get("metrics"),
            "written_plan": pick.get("plan"),
            "written_plan_adherence": reflection.get("plan_assessment", "not measured; prose goals are not structured in old logs"),
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", help="JSONL paths or glob patterns")
    ap.add_argument("--level", type=int, default=31)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    import glob
    paths = sorted({p for pattern in args.logs for p in glob.glob(pattern)})
    if not paths:
        ap.error("no log files matched")
    result = {"method": "Request mentions include repeated proposals; unique placements merge same-cell rebuilds. Historical blocked time is a sparse snapshot estimate. Written-plan adherence is not inferred from prose.",
              "attempts": [a for p in paths for a in attempts(p, args.level)]}
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
