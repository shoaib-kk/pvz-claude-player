"""Lifecycle and queue regressions; no game process or player calls."""
import unittest
from unittest.mock import Mock
import copy
import tempfile
from pathlib import Path
from pvz.player.execution import ExecutionTracker
from pvz.player.queueing import edit_queue, check_unit
from tests.test_campaign import action, board, operator, plant, seed
from pvz.agent import validate, decision_context, decision_reason
from pvz.player.journal import Journal


class TrackingTests(unittest.TestCase):
    def test_wait_cancel_and_completion_are_distinct_and_accounted(self):
        now = [0.0]
        events = []
        t = ExecutionTracker("attempt1", lambda **r: events.append(r), lambda: now[0])
        a = t.issue({"type": "plant", "seed": "fume_shroom", "row": 1, "col": 1}, 1)
        b = t.issue({"type": "plant", "seed": "sun_shroom", "row": 4, "col": 0}, 1)
        t.waiting(a, "sun")
        t.sample(True, 25)
        now[0] = 34
        t.finish(a, "canceled", "decision 2")
        t.finish(b, "completed")
        t.sample(False, 0)
        self.assertEqual(t.actions[a["id"]]["waits"], {"sun": 34})
        self.assertEqual(t.metrics()["planted"], {"sun_shroom": 1})
        self.assertEqual(t.metrics()["queue_stalled_unspent_sun_seconds"], 34)
        self.assertIn("waited sun 34s", t.report())
        self.assertNotIn("should", t.compact())
        self.assertEqual(len({r["event_id"] for r in events}), len(events))

    def test_unfinished_is_not_canceled_and_end_is_idempotent(self):
        log = Mock()
        tracker = ExecutionTracker("a", log)
        a = tracker.issue(action("sunflower", 0, 0), 1)
        tracker.end([a], "lost")
        tracker.end([a], "lost")
        self.assertEqual(tracker.actions[a["id"]]["status"], "unfinished")
        self.assertEqual(sum(c.kwargs["kind"] == "execution_summary" for c in log.call_args_list), 1)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ExecutionTracker("attempt", Mock())
        self.q = [self.tracker.issue(action("sun_shroom", 4, 0), 1)]

    def test_keep_append_and_cancel_preserve_ids(self):
        self.assertEqual(edit_queue(self.q, {"edit": "keep"}, self.tracker, 2), self.q)
        q = edit_queue(self.q, {"edit": "append", "actions": [action("puff_shroom", 1, 1)]}, self.tracker, 3)
        self.assertEqual([a["id"] for a in q], [1, 2])
        q = edit_queue(q, {"edit": "cancel", "cancel": [1]}, self.tracker, 4)
        self.assertEqual([a["id"] for a in q], [2])
        self.assertEqual(self.tracker.actions[1]["status"], "canceled")

    def test_replacement_retains_existing_move_and_its_wait_history(self):
        self.tracker.waiting(self.q[0], "sun")
        q = edit_queue(self.q, {"edit": "replace", "actions": [dict(self.q[0], independent=True)]}, self.tracker, 2)
        self.assertEqual(q[0]["id"], 1)
        self.assertEqual(len(self.tracker.actions), 1)
        self.assertEqual(self.tracker.actions[1]["status"], "waiting")

    def test_late_answer_cannot_resurrect_completed_id(self):
        self.tracker.finish(self.q[0], "completed")
        q = edit_queue([], {"edit": "replace", "actions": self.q}, self.tracker, 2)
        self.assertEqual(q, [])
        self.assertEqual(len(self.tracker.actions), 1)

    def test_no_id_echo_of_inflight_completion_is_also_ignored(self):
        s = board()
        plant(s, "sun_shroom", 4, 0)
        self.tracker.finish(self.q[0], "completed")
        d = {"edit": "replace", "actions": [action("sun_shroom", 4, 0)], "_queue_ids": [1]}
        self.assertEqual(edit_queue([], d, self.tracker, 2, s), [])
        # A later intentional rebuild is a new action, even at the same target.
        q = edit_queue([], {**d, "_queue_ids": []}, self.tracker, 3, board())
        self.assertEqual(q[0]["id"], 2)

    def test_invalid_edit_does_not_cancel_old_queue(self):
        with self.assertRaises(ValueError):
            edit_queue(self.q, {"edit": "replace", "actions": [dict(self.q[0], col=7)]}, self.tracker, 2)
        self.assertEqual(self.tracker.actions[1]["status"], "queued")

    def test_append_can_intentionally_repeat_a_conveyor_move(self):
        q = edit_queue(self.q, {"edit": "append", "actions": [action("sun_shroom", 4, 0)]}, self.tracker, 2)
        self.assertEqual([a["id"] for a in q], [1, 2])
        q = edit_queue(q, {"edit": "replace", "actions": [action("sun_shroom", 4, 0), action("sun_shroom", 4, 0)]}, self.tracker, 3)
        self.assertEqual([a["id"] for a in q], [1, 2])

    def test_canceling_group_does_not_leave_a_partial_dependency(self):
        moves = [dict(action("lily_pad", 2, 1), group=1), dict(action("fume_shroom", 2, 1), group=1)]
        q = edit_queue([], {"edit": "replace", "actions": moves}, self.tracker, 2)
        self.assertEqual(edit_queue(q, {"edit": "cancel", "cancel": [q[0]["id"]]}, self.tracker, 3), [])

    def test_groups_do_not_spend_until_all_steps_are_funded(self):
        s = board("fog")
        s["sun"] = 50
        seed(s, "lily_pad", cost=25)
        seed(s, "fume_shroom", cost=75)
        moves = [action("lily_pad", 2, 1), action("fume_shroom", 2, 1)]
        before = copy.deepcopy(s)
        self.assertEqual(check_unit(moves, s, validate)[0], "later")
        self.assertEqual(s, before)
        s["sun"] = 100
        self.assertEqual(check_unit(moves, s, validate)[0], "ok")

    def test_group_cannot_wait_forever_for_same_recharging_packet(self):
        s = board()
        seed(s, "sun_shroom", cost=25)
        moves = [action("sun_shroom", 0, 0), action("sun_shroom", 1, 0)]
        self.assertEqual(check_unit(moves, s, validate)[0], "reject")

    def test_independent_action_bypasses_wait_but_ordered_action_does_not(self):
        for independent in (False, True):
            with self.subTest(independent=independent):
                op = operator()
                s = board()
                s["sun"] = 25
                seed(s, "fume_shroom", cost=75)
                seed(s, "puff_shroom", cost=0)
                seed(s, "sun_shroom", cost=25)
                op.execution = ExecutionTracker("test", op.log)
                op.queue = [op.execution.issue(action("fume_shroom", 1, 1), 1),
                            op.execution.issue(dict(action("puff_shroom", 1, 3), independent=independent), 1),
                            op.execution.issue(dict(action("sun_shroom", 4, 0), independent=independent), 1)]
                op.snapshot = Mock(return_value=s)
                op.perform = Mock(return_value=True)
                op.work_queue()
                self.assertEqual(op.perform.call_count, 2 if independent else 0)
                self.assertEqual(len(op.queue), 1 if independent else 3)

    def test_live_failure_interrupts_remaining_group_steps(self):
        op = operator()
        s = board("fog")
        seed(s, "lily_pad", cost=25)
        seed(s, "fume_shroom", cost=75)
        op.execution = self.tracker
        moves = [dict(action("lily_pad", 2, 1), group=1), dict(action("fume_shroom", 2, 1), group=1)]
        op.queue = edit_queue([], {"actions": moves}, self.tracker, 1)
        op.snapshot = Mock(return_value=s)
        op.perform = Mock(return_value=False)
        op.work_queue()
        op.perform.assert_called_once()
        self.assertEqual(op.queue, [])
        self.assertEqual([r["status"] for r in self.tracker.actions.values()], ["queued", "failed", "rejected"])

    def test_successful_group_runs_requested_support_and_plant_in_order(self):
        op = operator()
        s = board("fog")
        s["sun"] = 100
        seed(s, "lily_pad", cost=25)
        seed(s, "fume_shroom", cost=75)
        op.execution = self.tracker
        moves = [dict(action("lily_pad", 2, 1), group=1), dict(action("fume_shroom", 2, 1), group=1)]
        op.queue = edit_queue([], {"actions": moves}, self.tracker, 1)
        op.snapshot = Mock(side_effect=lambda: copy.deepcopy(s))
        def perform(a, packet, state):
            plant(s, a["seed"], a["row"], a["col"])
            s["sun"] -= packet["cost"]
            s["seeds"][packet["slot"]]["ready"] = False
            return True
        op.perform = Mock(side_effect=perform)
        op.work_queue()
        self.assertEqual([c.args[0]["seed"] for c in op.perform.call_args_list], ["lily_pad", "fume_shroom"])
        self.assertEqual(s["sun"], 0)
        self.assertEqual(op.queue, [])


class ReflectionTests(unittest.TestCase):
    def test_evidence_stays_in_history_and_survives_unchanged_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            response = {"summary": "a fact", "general_lessons": ["my lesson"],
                        "situation_lessons": [], "observed": [{"fact": "recorded", "evidence": ["e1", "invented"]}],
                        "hypothesis": "my hypothesis", "next_attempt": "my experiment", "plan_assessment": "not executed",
                        "lesson_evidence": [{"scope": "general", "index": 1, "evidence": ["e1", "invented"]}]}
            brain = Mock()
            brain.plan_effort = None
            brain.ask.return_value = response
            j.reflect(brain, "4-1", "lost", "[e1] action completed", "fog", "my plan",
                      attempt="a1", evidence={"e1": {"event": "completed"}})
            h = j.data["history"][-1]
            self.assertEqual(h["observed"][0]["evidence"], ["e1"])
            self.assertEqual(h["lesson_evidence"][0]["attempt"], "a1")
            self.assertIn("my experiment", j.prompt_block("fog"))
            self.assertNotIn("e1", j.prompt_block("fog"))
            self.assertNotIn("my hypothesis", j.prompt_block("fog"))
            brain.ask.return_value = {**response, "lesson_evidence": []}
            j.reflect(brain, "4-1", "lost", "report", "fog", attempt="a2")
            self.assertEqual(j.data["history"][-1]["lesson_evidence"][0]["attempt"], "a1")
            self.assertEqual(Journal(Path(tmp)).lessons, ["my lesson"])

    def test_empty_lessons_can_still_carry_the_players_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            j.data["history"] = [{"situation": "fog", "next_attempt": "my experiment"}]
            self.assertIn("my experiment", j.prompt_block("fog"))


class FreeCardTests(unittest.TestCase):
    def test_free_card_wakes_empty_queue_but_idle_checks_back_off(self):
        s = board()
        s["sun"] = 0
        p = seed(s, "puff_shroom", ready=False, cost=0)
        old = decision_context(s)
        p["ready"] = True
        current = decision_context(s)
        opts = dict(conveyor=False, queued=False, completed=False)
        self.assertEqual(decision_reason(current, old, since=8, fruitless=0, **opts), "card_available")
        self.assertIsNone(decision_reason(current, current, since=8, fruitless=0, **opts))
        self.assertEqual(decision_reason(current, current, since=30, fruitless=0, **opts), "idle_check")
        self.assertIsNone(decision_reason(current, current, since=30, fruitless=4, **opts))
        self.assertEqual(decision_reason(current, current, since=120, fruitless=4, **opts), "idle_check")

    def test_vasebreaker_with_nothing_queued_asks_again(self):
        s = board()
        s["sun"], s["special"] = 0, "vases"
        s["items"] = [{"type": "vase", "row": 0, "col": 5}]
        current = decision_context(s)
        opts = dict(conveyor=False, queued=False, completed=False)
        self.assertIsNone(decision_reason(current, current, since=10, fruitless=5, **opts))
        self.assertEqual(decision_reason(current, current, since=30, fruitless=5, **opts), "vase_idle")
        self.assertIsNone(decision_reason(current, current, since=30, fruitless=5,
                                          conveyor=False, queued=True, completed=False))


if __name__ == "__main__":
    unittest.main()
