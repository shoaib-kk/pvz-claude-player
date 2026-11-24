"""Bounded, timestamped feedback with acknowledgement at accepted decisions."""
from collections import deque
import time


class FeedbackLog:
    def __init__(self, clock=None, capacity=128):
        self.clock = clock or time.monotonic
        self.events = deque(maxlen=capacity)
        self.sequence = 0
        self.acknowledged = 0

    def add(self, text):
        self.sequence += 1
        self.events.append({"id": self.sequence, "at": self.clock(), "text": text})

    def snapshot(self, limit=8):
        """Capture a request watermark without acknowledging it or later arrivals."""
        if limit < 1:
            raise ValueError("feedback limit must be positive")
        now, cursor = self.clock(), self.sequence
        fresh = [e for e in self.events if self.acknowledged < e["id"] <= cursor][-limit:]
        rows = [{"id": e["id"], "text": e["text"],
                 "age_seconds": round(max(0, now - e["at"]), 1)} for e in fresh]
        omitted = cursor - self.acknowledged - len(rows)
        return rows, cursor, omitted

    def acknowledge(self, cursor):
        if type(cursor) is not int or not 0 <= cursor <= self.sequence:
            raise ValueError("invalid feedback watermark")
        self.acknowledged = max(self.acknowledged, cursor)


def feedback_lines(recent, omitted=0):
    if not recent and not omitted:
        return []
    if recent and isinstance(recent[0], str):
        # Historical prompts and read-only callers remain readable.
        return ["", "Results of your recent actions, and things that happened:",
                *(f"  {r}" for r in dict.fromkeys(recent[-8:]))]
    lines = ["", "New feedback since the previous accepted decision "
             "(ages at this observation; current board and queue are authoritative):"]
    if omitted:
        lines.append(f"  {omitted} older new events omitted to bound prompt size.")
    lines.extend(f"  [{'~' if e.get('approximate_age') else ''}{e['age_seconds']:g}s ago] {e['text']}"
                 for e in recent[-8:])
    return lines
