"""Token usage of the in-game player only.

Every call the player makes (plant pick + plan, plan, gameplay decisions, journal
reflection) is logged with the usage Claude reported for it. Nothing an operator does
(running scripts, reading logs, brain_check.py, test probes) is in these logs, so the
totals here are purely what playing the game cost.

  .venv\\Scripts\\python.exe usage_report.py                 # all runs
  .venv\\Scripts\\python.exe usage_report.py --since 2026-11-19
  .venv\\Scripts\\python.exe usage_report.py logs\\run_X.jsonl  # specific runs

Note: your Claude plan's usage meter counts everything on the account, including an
operator using Claude, so it can't separate the two; this report can.
Older logs only recorded usage for gameplay decisions.
"""
import argparse
import glob
import json
import os
from collections import defaultdict

CALL_KINDS = {"decision": "decisions", "seed_pick": "pick + plan", "level_plan": "plan",
              "journal": "reflection"}
FIELDS = ("calls", "input", "cache_write", "cache_read", "output", "thinking")


def tokens(usage):
    u = usage or {}
    details = u.get("output_tokens_details") or {}
    return {
        "input": u.get("input_tokens") or 0,
        "cache_write": u.get("cache_creation_input_tokens") or 0,
        "cache_read": u.get("cache_read_input_tokens") or 0,
        "output": u.get("output_tokens") or 0,
        "thinking": details.get("thinking_tokens") or 0,
    }


def collect(paths):
    by_kind = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    by_level = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    levels_played = 0
    def add(kind, level, usage):
        t = tokens(usage)
        for bucket in (by_kind[CALL_KINDS[kind]], by_level[level]):
            bucket["calls"] += 1
            for k, v in t.items():
                bucket[k] += v

    for path in paths:
        level = "?"
        picks = []        # the plant pick happens before its level_start line
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = r.get("kind")
            if kind == "level_start":
                lv = r.get("level")
                level = f"{(lv - 1) // 10 + 1}-{(lv - 1) % 10 + 1}" if lv else "?"
                levels_played += 1
                for usage in picks:
                    add("seed_pick", level, usage)
                picks = []
            if kind not in CALL_KINDS or not r.get("usage"):
                continue
            if kind == "seed_pick":
                picks.append(r["usage"])
            else:
                add(kind, level, r["usage"])
        for usage in picks:
            add("seed_pick", "?", usage)
    return by_kind, by_level, levels_played


def table(title, rows):
    print(f"\n{title}")
    print(f"  {'':16}" + "".join(f"{f:>12}" for f in FIELDS))
    total = dict.fromkeys(FIELDS, 0)
    for name, row in rows:
        print(f"  {name:16}" + "".join(f"{row[f]:>12,}" for f in FIELDS))
        for f in FIELDS:
            total[f] += row[f]
    print(f"  {'TOTAL':16}" + "".join(f"{total[f]:>12,}" for f in FIELDS))
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="*", help="run logs (default: all logs/run_*.jsonl)")
    ap.add_argument("--since", help="only runs from this date on (YYYY-MM-DD)")
    args = ap.parse_args()
    root = os.path.dirname(os.path.abspath(__file__))
    paths = args.logs or sorted(glob.glob(os.path.join(root, "logs", "run_*.jsonl")))
    if args.since:
        stamp = args.since.replace("-", "")
        paths = [p for p in paths if os.path.basename(p)[4:14].replace("-", "") >= stamp]
    by_kind, by_level, played = collect(paths)
    print(f"{len(paths)} run log(s), {played} level attempt(s). Player calls only; operator usage excluded.")
    table("By call type", sorted(by_kind.items()))
    total = table("By level", sorted(by_level.items()))
    if played:
        print(f"\nPer level attempt: {total['calls'] / played:.0f} calls, "
              f"{(total['input'] + total['cache_write'] + total['cache_read']) / played:,.0f} input tokens "
              f"(incl. cache), {total['output'] / played:,.0f} output tokens")


if __name__ == "__main__":
    main()
