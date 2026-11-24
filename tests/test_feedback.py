"""Feedback freshness and factual firing relationships, with no game or player calls."""
import unittest
from pvz.player.feedback import FeedbackLog, feedback_lines
from pvz.player import brains
from tests.test_campaign import operator, board, plant


class FeedbackTests(unittest.TestCase):
    def test_acknowledges_only_the_captured_batch_not_events_during_thinking(self):
        now = [100.0]
        log = FeedbackLog(lambda: now[0])
        log.add("pot disappeared")
        now[0] = 105
        rows, cursor, omitted = log.snapshot()
        self.assertEqual(rows, [{"id": 1, "text": "pot disappeared", "age_seconds": 5.0}])
        self.assertEqual(omitted, 0)
        log.add("mower fired during the call")
        log.acknowledge(cursor)
        rows, cursor, _ = log.snapshot()
        self.assertEqual([r["text"] for r in rows], ["mower fired during the call"])
        log.acknowledge(cursor)
        self.assertEqual(log.snapshot()[0], [])

    def test_failed_reply_retries_feedback_and_age_increases(self):
        now = [10.0]
        log = FeedbackLog(lambda: now[0])
        log.add("wall lost")
        first = log.snapshot()
        now[0] = 24
        retry = log.snapshot()
        self.assertEqual(first[1], retry[1])
        self.assertEqual(retry[0][0]["age_seconds"], 14)
        self.assertIn("[14s ago] wall lost", "\n".join(feedback_lines(retry[0])))

    def test_overflow_is_bounded_and_reported(self):
        log = FeedbackLog(lambda: 0, capacity=10)
        for i in range(25):
            log.add(f"event {i}")
        rows, cursor, omitted = log.snapshot(limit=8)
        self.assertEqual((len(rows), cursor, omitted), (8, 25, 17))
        self.assertIn("17 older new events omitted", "\n".join(feedback_lines(rows, omitted)))
        log.acknowledge(cursor)
        self.assertEqual(log.snapshot(), ([], 25, 0))

    def test_identical_events_are_distinct_but_old_watermarks_cannot_resurrect_them(self):
        log = FeedbackLog(lambda: 0)
        log.add("OK plant sunflower at (0,0)")
        log.add("OK plant sunflower at (0,0)")
        self.assertEqual(len(log.snapshot()[0]), 2)
        log.acknowledge(2)
        log.acknowledge(1)
        self.assertEqual(log.snapshot()[0], [])

    def test_agent_acknowledges_valid_reply_and_preserves_inflight_arrivals(self):
        op = operator()
        op.add_feedback("observed before request")
        _, cursor, _ = op.feedback.snapshot()
        op.add_feedback("arrived while thinking")
        op.apply_decision({"reasoning": "wait", "edit": "keep", "actions": [],
                           "_think": 0, "_state": board(), "_usage": {}, "_feedback_cursor": cursor})
        self.assertEqual([r["text"] for r in op.feedback.snapshot()[0]], ["arrived while thinking"])

    def test_agent_does_not_acknowledge_errors_or_invalid_queue_edits(self):
        for invalid in (False, True):
            with self.subTest(invalid_queue_edit=invalid):
                op = operator()
                op.add_feedback("pot lost")
                _, cursor, _ = op.feedback.snapshot()
                decision = {"reasoning": "r", "_think": 0, "_state": board(), "_usage": {},
                            "_feedback_cursor": cursor}
                decision.update({"edit": "replace", "actions": [{"type": "plant"}]}
                                if invalid else {"_error": True})
                op.apply_decision(decision)
                self.assertEqual(op.feedback.acknowledged, 0)
                self.assertEqual(op.feedback.snapshot()[0][0]["text"], "pot lost")

    def test_empty_fresh_feedback_costs_no_prompt_section(self):
        self.assertEqual(feedback_lines([]), [])


class FiringRelationTests(unittest.TestCase):
    def test_house_side_zombie_is_explicitly_past_forward_attackers(self):
        s = board("roof")
        plant(s, "cabbage_pult", 0, 3)
        plant(s, "peashooter", 0, 4)
        s["zombies"] = [{"type": "conehead", "row": 0, "x": 114, "hp": 270, "armor_hp": 10}]
        text = brains.describe(s, [], compact=True)
        self.assertIn("closest zombie has passed forward shooters at cols 3,4", text)
        self.assertIn("0 with the closest zombie in their firing direction", text)

    def test_backward_shooter_and_attacker_on_house_side_are_not_marked_passed(self):
        s = board()
        plant(s, "peashooter", 0, 1)
        plant(s, "split_pea", 0, 7)
        s["zombies"] = [{"type": "zombie", "row": 0, "x": 380, "hp": 270, "armor_hp": 0}]
        self.assertNotIn("closest zombie has passed", brains.describe(s, []))

    def test_no_historical_feedback_or_range_guarantee_is_invented(self):
        s = board()
        plant(s, "peashooter", 0, 1)
        s["zombies"] = [{"type": "zombie", "row": 0, "x": 380, "hp": 270, "armor_hp": 0}]
        text = brains.describe(s, [])
        self.assertNotIn("New feedback", text)
        self.assertNotIn("can hit the closest zombie", text)


class ReplayFeedbackTests(unittest.TestCase):
    def test_recorded_queue_does_not_overwrite_the_decision_record(self):
        from pathlib import Path
        from tools.replay_decisions import recorded_cases
        path = Path("logs/run_2026-11-21_11-42-51_subscription.jsonl")
        if not path.exists():
            self.skipTest("recorded run is not available in this checkout")
        case = next(recorded_cases(path, [5]))
        self.assertEqual(case["row"]["n"], 5)
        self.assertTrue(case["queue"])
        self.assertTrue(all(type(a["row"]) is int for a in case["queue"]))

    def test_old_logs_exclude_seen_events_and_keep_arrivals_during_thinking(self):
        from tools.replay_decisions import fresh_recorded_feedback
        records = [
            {"kind": "level_start", "t": "2026-11-21T00:00:00"},
            {"kind": "event", "t": "2026-11-21T00:00:01", "text": "old event"},
            {"kind": "action", "t": "2026-11-21T00:00:08", "result": "OK {}",
             "action": {"type": "plant", "seed": "wall_nut", "row": 0, "col": 0}},
            {"kind": "decision", "n": 1, "t": "2026-11-21T00:00:10", "think_seconds": 4,
             "decision": {"reasoning": "r"}},
            {"kind": "event", "t": "2026-11-21T00:00:14", "text": "after second request"},
            {"kind": "decision", "n": 2, "t": "2026-11-21T00:00:16", "think_seconds": 3,
             "decision": {"reasoning": "r"}},
        ]
        events, omitted, provenance = fresh_recorded_feedback(records, 5, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "OK plant wall_nut at (0,0)")
        self.assertEqual(events[0]["age_seconds"], 5)
        self.assertTrue(events[0]["approximate_age"])
        self.assertEqual(omitted, 0)
        self.assertIn("estimated", provenance)
        legacy = fresh_recorded_feedback(records, 5, 0, fresh_only=False)[0]
        self.assertEqual(len(legacy), 2)

    def test_new_logs_reuse_captured_batch_without_reconstructing_times(self):
        from tools.replay_decisions import fresh_recorded_feedback
        events = [{"id": 4, "text": "pot lost", "age_seconds": 0.2}]
        row = {"kind": "decision", "feedback": events, "state": {"feedback_omitted": 3}}
        self.assertEqual(fresh_recorded_feedback([row], 0, 0), (events, 3, "recorded batch"))


if __name__ == "__main__":
    unittest.main()
