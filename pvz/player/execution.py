"""Factual action lifecycle tracking. This module makes no gameplay choices."""
from collections import Counter
import time


def action_key(action):
    return tuple(action.get(k) for k in ("type", "seed", "row", "col"))


def clean_action(action):
    return {k: v for k, v in action.items() if not k.startswith("_") and k != "id"}


class ExecutionTracker:
    def __init__(self, attempt, log, clock=None):
        self.attempt = attempt
        self.log = log
        self.clock = clock or time.monotonic
        self.actions = {}
        self.events = []
        self.started = self.clock()
        self.last_sample = self.started
        self.was_stalled_with_sun = False
        self.stalled_with_sun = 0.0
        self.ended = False

    def event(self, kind, **fields):
        event = {"event_id": f"e{len(self.events) + 1}", "attempt": self.attempt,
                 "event": kind, "elapsed": round(self.clock() - self.started, 2), **fields}
        self.events.append(event)
        self.log(kind="execution_event", **event)
        return event["event_id"]

    def issue(self, action, decision):
        ident = len(self.actions) + 1
        record = {"id": ident, "action": clean_action(action), "decision": decision,
                  "status": "queued", "waits": {}, "wait_start": None, "waiting_for": None}
        self.actions[ident] = record
        record["evidence"] = self.event("queued", action_id=ident, action=record["action"], decision=decision)
        return {**record["action"], "id": ident}

    def _close_wait(self, record):
        if record["wait_start"] is not None:
            reason = record["waiting_for"]
            record["waits"][reason] = record["waits"].get(reason, 0) + self.clock() - record["wait_start"]
            record["wait_start"] = None

    def waiting(self, action, reason):
        record = self.actions.get(action.get("id"))
        if not record or record["status"] in ("completed", "rejected", "failed", "canceled", "unfinished"):
            return
        if record["waiting_for"] == reason and record["wait_start"] is not None:
            return
        self._close_wait(record)
        record["waiting_for"], record["wait_start"] = reason, self.clock()
        record["status"] = "waiting"
        record["evidence"] = self.event("waiting", action_id=record["id"], reason=reason)

    def finish(self, action, status, reason=""):
        record = self.actions.get(action.get("id"))
        if not record:
            return
        self._close_wait(record)
        record["waiting_for"] = None
        record["status"] = status
        record["reason"] = reason
        record["evidence"] = self.event(status, action_id=record["id"], reason=reason,
                                         waits={k: round(v, 2) for k, v in record["waits"].items()})

    def sample(self, stalled, sun):
        now = self.clock()
        if self.was_stalled_with_sun:
            self.stalled_with_sun += now - self.last_sample
        self.last_sample = now
        self.was_stalled_with_sun = stalled and sun > 0

    def metrics(self):
        return {"issued": len(self.actions),
                "statuses": dict(Counter(r["status"] for r in self.actions.values())),
                "requested_plants": dict(Counter(r["action"].get("seed") for r in self.actions.values()
                                                 if r["action"]["type"] == "plant")),
                "planted": dict(Counter(r["action"].get("seed") for r in self.actions.values()
                                        if r["action"]["type"] == "plant" and r["status"] == "completed")),
                "queue_stalled_unspent_sun_seconds": round(self.stalled_with_sun, 2)}

    def compact(self):
        m = self.metrics()
        counts = ", ".join(f"{k} {v}" for k, v in m["statuses"].items()) or "none"
        seeds = ", ".join(f"{n} {m['planted'].get(n, 0)}/{k}" for n, k in m["requested_plants"].items())
        lines = [f"Execution ({self.attempt}): {counts}. Plants completed/issued: {seeds or 'none'}. "
                 f"Queue stalled with unspent sun: {m['queue_stalled_unspent_sun_seconds']:.0f}s."]
        waits = []
        for r in self.actions.values():
            if r["wait_start"] is not None:
                seconds = r["waits"].get(r["waiting_for"], 0) + self.clock() - r["wait_start"]
                waits.append((seconds, f"#{r['id']} {r['waiting_for']} {seconds:.0f}s"))
        if waits:
            lines.append("Waiting: " + "; ".join(t for _, t in sorted(waits, reverse=True)[:3]))
        return "\n".join(lines)

    def report(self):
        lines = ["[s0] " + self.compact(), "Execution history (IDs and evidence belong to this attempt):"]
        for r in self.actions.values():
            a = r["action"]
            waits = dict(r["waits"])
            if r["wait_start"] is not None:
                why = r["waiting_for"]
                waits[why] = waits.get(why, 0) + self.clock() - r["wait_start"]
            timing = ", ".join(f"{k} {v:.0f}s" for k, v in waits.items())
            lines.append(f"[{r['evidence']}] #{r['id']} {a.get('seed', a['type'])}@{a.get('row')},{a.get('col')}: "
                         f"{r['status']}; {r.get('reason', '')}" + (f"; waited {timing}" if timing else ""))
        return "\n".join(lines)

    def end(self, queue, outcome):
        if self.ended:
            return
        self.ended = True
        self.sample(False, 0)
        for a in queue:
            self.finish(a, "unfinished", f"attempt ended: {outcome}")
        self.log(kind="execution_summary", attempt=self.attempt, metrics=self.metrics())
