"""Offline regressions for placement affordances, real spending and player-owned objectives."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pvz.player import brains
from pvz.player.action_contract import check_action
from pvz.player.action_contract import validate_schema
from pvz.player.placement import legal_targets, legal_target_lines, validate
from pvz.player.purchase_accounting import PurchaseLedger
from pvz.player.plan_progress import PlanProgress
from pvz.player.journal import Journal, LevelRecorder
from pvz.player.queueing import edit_queue
from pvz.player.execution import ExecutionTracker
from tests.test_campaign import board, plant, seed, action


class LegalTargetsTests(unittest.TestCase):
    def test_last_roof_pot_remains_available_to_funded_blockers(self):
        s = board("roof")
        s["sun"] = 275
        plant(s, "flower_pot", 0, 0)
        for name, cost in (("wall_nut", 50), ("tall_nut", 125), ("cabbage_pult", 100)):
            seed(s, name, cost=cost)
        seed(s, "cherry_bomb", ready=False, cost=150)
        before = copy.deepcopy(s)
        targets = {x["seed"]: x for x in legal_targets(s)}
        for name in ("wall_nut", "tall_nut", "cabbage_pult"):
            self.assertEqual(targets[name]["rows"], {0: [0]})
            self.assertTrue(targets[name]["ready"] and targets[name]["affordable"])
        self.assertEqual(targets["cherry_bomb"]["rows"], {0: [0]})
        self.assertFalse(targets["cherry_bomb"]["ready"])
        self.assertEqual(s, before)

    def test_supports_water_occupied_graves_and_funding_are_separate(self):
        s = board("pool")
        s["sun"] = 0
        for name, cost in (("peashooter", 100), ("lily_pad", 25), ("grave_buster", 75)):
            seed(s, name, cost=cost)
        plant(s, "lily_pad", 2, 1)
        plant(s, "wall_nut", 0, 0)
        s["grid"][0][0] = "wall_nut"
        s["items"] = [{"type": "grave", "row": 1, "col": 3}]
        targets = {x["seed"]: x for x in legal_targets(s)}
        self.assertEqual(targets["peashooter"]["rows"][2], [1])
        self.assertNotIn(0, targets["peashooter"]["rows"][0])
        self.assertNotIn(3, targets["peashooter"]["rows"][1])
        self.assertEqual(targets["grave_buster"]["rows"], {1: [3]})
        self.assertFalse(targets["peashooter"]["affordable"])
        self.assertIn("Use sun/recharge in Seeds above", "\n".join(legal_target_lines(s)))

    def test_bowling_boss_and_upgrades_use_the_executor_rules(self):
        s = board(special="bowling")
        seed(s, "wall_nut")
        self.assertTrue(all(cols == [0, 1, 2] for cols in legal_targets(s)[0]["rows"].values()))
        s = board("boss", "boss")
        seed(s, "cabbage_pult")
        plant(s, "flower_pot", 0, 8)
        plant(s, "flower_pot", 0, 7)
        self.assertEqual(legal_targets(s)[0]["rows"], {0: [7]})
        s = board()
        seed(s, "gatling_pea", cost=250)
        plant(s, "repeater", 1, 2)
        self.assertEqual(legal_targets(s)[0]["rows"], {1: [2]})

    def test_recorded_emergency_boards_expose_house_end_options(self):
        path = Path("logs/run_2026-11-21_11-42-51_subscription.jsonl")
        if not path.exists():
            self.skipTest("recorded local run is not in this checkout")
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        for n in (107, 108):
            state = next(x["state"] for x in rows if x["kind"] == "decision" and x["n"] == n)
            targets = {x["seed"]: x for x in legal_targets(state)}
            for name in ("wall_nut", "tall_nut", "cabbage_pult"):
                self.assertIn(0, targets[name]["rows"][0])
                self.assertEqual(validate(action(name, 0, 0), state)[0], "ok")
            self.assertIn("Legal planting cells now", brains.describe(state, [], compact=True))

    def test_replay_does_not_show_actions_from_the_decision_being_replayed(self):
        from tools.replay_decisions import recorded_cases
        path = Path("logs/run_2026-11-21_11-42-51_subscription.jsonl")
        if not path.exists():
            self.skipTest("recorded local run is not in this checkout")
        for case in recorded_cases(path, [84, 107, 108]):
            self.assertEqual(case["queue"], [])

    def test_identical_targets_share_one_list_without_losing_packet_names(self):
        s = board("roof")
        plant(s, "flower_pot", 0, 0)
        seed(s, "wall_nut", cost=50)
        seed(s, "tall_nut", ready=False, cost=125)
        out = "\n".join(legal_target_lines(s))
        self.assertIn("wall_nut, tall_nut: r0:0", out)
        self.assertEqual(out.count("r0:0"), 1)


class ContractTests(unittest.TestCase):
    def test_missing_seed_coordinates_slot_numbers_and_booleans_are_rejected(self):
        valid = {"reasoning": "r", "edit": "append", "actions": [action("wall_nut", 0, 0)]}
        schema = brains.decision_schema(["wall_nut"])
        validate_schema(valid, schema)
        malformed = [
            {"type": "plant", "row": 0, "col": 0},
            {"type": "plant", "seed": "0", "row": 0, "col": 0},
            {"type": "plant", "seed": "wall_nut", "col": 0},
            action("wall_nut", True, 0), action("wall_nut", 0, 9), action("sunflower", 0, 0),
        ]
        for a in malformed:
            with self.subTest(action=a), self.assertRaises(ValueError):
                validate_schema({**valid, "actions": [a]}, schema)
        validate_schema({**valid, "actions": [{"type": "shovel", "row": 0, "col": 0}]}, schema)
        validate_schema({**valid, "actions": [{"type": "break_vase", "row": 5, "col": 8}]}, schema)

    def test_invalid_action_keeps_previous_queue_untouched(self):
        tracker = ExecutionTracker("test", Mock())
        q = [tracker.issue(action("sunflower", 0, 0), 1)]
        with self.assertRaises(ValueError):
            edit_queue(q, {"edit": "replace", "actions": [{"type": "plant", "row": 0, "col": 0}]}, tracker, 2)
        self.assertEqual(tracker.actions[1]["status"], "queued")
        self.assertEqual(len(tracker.actions), 1)


class AccountingTests(unittest.TestCase):
    def test_shovel_tracks_the_layer_actually_removed(self):
        s = board()
        plant(s, "wall_nut", 0, 0)
        plant(s, "pumpkin", 0, 0)
        ledger = PurchaseLedger()
        ledger.observe(s)
        after = copy.deepcopy(s)
        after["plants"] = [p for p in after["plants"] if p["type"] != "pumpkin"]
        ledger.shoveled({"type": "shovel", "row": 0, "col": 0}, s, after)
        ledger.observe(after)
        m = ledger.metrics()
        self.assertEqual(m["intentional_removals_or_upgrades"], {"pumpkin": 1})
        self.assertEqual(m["replacement_value_disappeared"], 0)
        self.assertIn((0, 0, "wall_nut"), ledger.active)

    def test_free_starting_pots_are_not_purchase_spending(self):
        s = board("roof")
        for col in range(4):
            for row in range(5):
                plant(s, "flower_pot", row, col)
        packet = seed(s, "flower_pot", cost=25)
        rec = LevelRecorder("5-2")
        rec.observe(s)
        # Lose the 20 free pots, then buy and lose 15 pots, and retain 5 purchases.
        s["plants"] = []
        rec.observe(s)
        for i in range(20):
            a = action("flower_pot", i % 5, 4 + i // 5)
            rec.record_action(a, packet, s)
            plant(s, "flower_pot", a["row"], a["col"])
            rec.observe(s)
            if i < 15:
                s["plants"] = [p for p in s["plants"] if not (p["row"] == a["row"] and p["col"] == a["col"])]
                rec.observe(s)
        m = rec.purchases.metrics()
        self.assertEqual(m["initial_plants"], {"flower_pot": 20})
        self.assertEqual(m["packet_sun_spent"], 500)
        self.assertEqual(m["replacement_value_disappeared"], 875)
        self.assertEqual(m["purchased_disappeared_spend"], 375)
        self.assertEqual(m["disappeared_by_origin"]["initial"], {"flower_pot": 20})
        self.assertIn("NOT cash spent", rec.report())

    def test_unknown_price_consumables_and_shovels_are_not_fabricated_losses(self):
        s = board()
        ledger = PurchaseLedger()
        ledger.observe(s)
        a = action("sunflower", 0, 0)
        ledger.purchased(a, {"name": "sunflower", "cost": None}, s)
        plant(s, "sunflower", 0, 0)
        ledger.observe(s)
        ledger.shoveled({"type": "shovel", "row": 0, "col": 0}, s)
        s["plants"] = []
        s["grid"][0][0] = None
        ledger.observe(s)
        ledger.purchased(action("cherry_bomb", 0, 0), {"name": "cherry_bomb", "cost": 150}, s)
        ledger.observe(s)  # instantaneous plant can disappear between observations
        m = ledger.metrics()
        self.assertEqual(m["packet_sun_spent"], 150)
        self.assertEqual(m["unknown_cost_purchases"], {"sunflower": 1})
        self.assertEqual(m["purchased_disappeared_spend"], 0)
        self.assertEqual(m["replacement_value_disappeared"], 0)


class ProgressAndHistoryTests(unittest.TestCase):
    def test_deadline_uses_confirmation_wave_not_the_pre_click_wave(self):
        rec = LevelRecorder("5-2", objectives=[{"label": "my timing", "seed": "wall_nut",
                                               "count": 1, "before_wave": 2}])
        s = board("roof")
        s["wave"] = [1, 20]
        plant(s, "flower_pot", 0, 0)
        packet = seed(s, "wall_nut", cost=50)
        after = copy.deepcopy(s)
        after["wave"] = [2, 20]
        plant(after, "wall_nut", 0, 0)
        rec.record_action(action("wall_nut", 0, 0), packet, s, after)
        self.assertEqual(rec.progress.status(after)[0]["status"], "deadline missed")
        self.assertEqual(rec.purchases.metrics()["packet_sun_spent"], 50)

    def test_goals_record_real_completion_deadline_and_current_presence(self):
        progress = PlanProgress([{"label": "my experiment", "seed": "tall_nut", "count": 1,
                                  "row": 2, "before_wave": 2}])
        s = board("roof")
        s["wave"] = [1, 20]
        self.assertEqual(progress.status(s)[0]["status"], "pending")
        progress.purchased(action("tall_nut", 1, 2), s)  # wrong row does not count
        s["wave"] = [3, 20]
        progress.purchased(action("tall_nut", 2, 2), s)  # late completion does not meet deadline
        plant(s, "tall_nut", 2, 2)
        row = progress.status(s)[0]
        self.assertEqual((row["completed"], row["completed_on_time"], row["currently_present"]), (1, 0, 1))
        self.assertEqual(row["status"], "deadline missed")
        self.assertEqual(progress.objectives[0]["seed"], "tall_nut")

    def test_selection_keeps_furthest_result_and_recent_attempts_without_editing_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            j.data["history"] = [{"level": "5-2", "outcome": "lost", "t": str(i),
                                  "attempt_facts": {"wave": [wave, 20], "loadout": [name]}}
                                 for i, wave, name in ((1, 20, "squash"), (2, 5, "peashooter"),
                                                       (3, 8, "wall_nut"), (4, 12, "cabbage_pult"))]
            before = copy.deepcopy(j.data)
            text = j.prompt_block("roof", "5-2")
            self.assertIn("wave 20/20; loadout squash", text)
            self.assertIn("wave 12/20; loadout cabbage_pult", text)
            self.assertNotIn("loadout peashooter", text)
            self.assertIn("starting cleaners not recorded", text)
            self.assertEqual(j.data, before)


if __name__ == "__main__":
    unittest.main()
