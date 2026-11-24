"""Offline arithmetic and prompt regressions; no game reads or player calls."""
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock

from pvz.player import brains
from pvz.player.journal import Journal, REFLECT_SYSTEM
from pvz.player.sun_accounting import MECHANICS_AND_EVIDENCE, accounting_lines, sun_accounting, verified_costs
from tests.test_campaign import action, board, plant, seed


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.state = board("fog")
        self.state["sun"] = 45
        seed(self.state, "fume_shroom", cost=75)
        seed(self.state, "puff_shroom", cost=0)
        seed(self.state, "sun_shroom", cost=25)
        self.queue = [dict(action("fume_shroom", 1, 1), id=4)]

    def test_free_packet_preserves_both_balance_and_queued_purchase_gap(self):
        result = sun_accounting(self.state, self.queue)
        rows = {r["seed"]: r for r in result["packets"]}
        self.assertEqual(result["wait_shortfall"], 30)
        self.assertEqual(rows["puff_shroom"]["sun_after"], 45)
        self.assertEqual(rows["puff_shroom"]["reference_shortfall"], 30)
        self.assertEqual(rows["puff_shroom"]["extra_shortfall"], 0)
        self.assertEqual(rows["sun_shroom"]["sun_after"], 20)
        self.assertEqual(rows["sun_shroom"]["reference_shortfall"], 55)
        self.assertFalse(rows["fume_shroom"]["affordable"])
        self.assertIsNone(rows["fume_shroom"]["sun_after"])

    def test_accounting_is_generic_and_does_not_select_or_reorder_actions(self):
        seed(self.state, "unfamiliar_free_packet", cost=0)
        before_state, before_queue = copy.deepcopy(self.state), copy.deepcopy(self.queue)
        result = sun_accounting(self.state, self.queue)
        row = next(r for r in result["packets"] if r["seed"] == "unfamiliar_free_packet")
        self.assertEqual(row["sun_after"], 45)
        self.assertEqual(row["extra_shortfall"], 0)
        self.assertEqual(self.state, before_state)
        self.assertEqual(self.queue, before_queue)

    def test_unknown_cost_is_never_assumed_free(self):
        seed(self.state, "mystery_packet", cost=None)
        result = sun_accounting(self.state, self.queue)
        self.assertNotIn("mystery_packet", [r["seed"] for r in result["packets"]])
        self.assertIsNone(verified_costs(self.state)["mystery_packet"])

    def test_cooling_packets_are_not_presented_as_ready_purchases(self):
        self.state["seeds"][1]["ready"] = False
        result = sun_accounting(self.state, self.queue)
        self.assertNotIn("puff_shroom", [r["seed"] for r in result["packets"]])

    def test_reference_packet_is_not_counted_as_competing_with_itself(self):
        self.state["sun"] = 100
        result = sun_accounting(self.state, self.queue)
        row = next(r for r in result["packets"] if r["seed"] == "fume_shroom")
        self.assertEqual(row["sun_after"], 25)
        self.assertIsNone(row["reference_shortfall"])

    def test_no_queue_no_fabricated_saving_goal(self):
        result = sun_accounting(self.state)
        self.assertIsNone(result["reference"])
        self.assertTrue(all(r["reference_shortfall"] is None for r in result["packets"]))

    def test_free_water_packet_and_paid_support_remain_distinct(self):
        seed(self.state, "sea_shroom", cost=0)
        seed(self.state, "lily_pad", cost=25)
        rows = {r["seed"]: r for r in sun_accounting(self.state, self.queue)["packets"]}
        self.assertEqual(rows["sea_shroom"]["sun_after"], 45)
        self.assertEqual(rows["lily_pad"]["sun_after"], 20)
        out = brains.describe(self.state, [], self.queue, compact=True)
        self.assertIn("supports, group costs and queue order are separate", out)
        self.assertIn("puff_shroom: 45-0=45 sun; fume_shroom shortfall 30 (extra 0)", out)

    def test_observed_income_fact_uses_only_awake_producers(self):
        out = "\n".join(accounting_lines(self.state, self.queue))
        self.assertIn("Observed awake sun producers: 0", out)
        plant(self.state, "sunflower", 0, 0, asleep=True)
        self.assertIn("Observed awake sun producers: 0", "\n".join(accounting_lines(self.state)))
        plant(self.state, "sun_shroom", 1, 0)
        self.assertIn("Observed awake sun producers: 1", "\n".join(accounting_lines(self.state)))


class EvidencePromptTests(unittest.TestCase):
    def test_mechanics_precedence_applies_to_deciding_choosing_planning_and_reflecting(self):
        brain = brains.Notes()
        brain.notes = "My hypothesis: avoid an option to save sun."
        for base in (brains.SYSTEM_PROMPT, brains.PICK_SYSTEM, brains.PLAN_SYSTEM):
            self.assertIn(MECHANICS_AND_EVIDENCE, brain.system(base))
        self.assertIn(MECHANICS_AND_EVIDENCE, REFLECT_SYSTEM)
        self.assertIn("A 0-sun packet spends", brain.system(brains.PICK_SYSTEM))
        self.assertIn("separately purchased support", brain.system(brains.SYSTEM_PROMPT))

    def test_no_free_plant_is_forced_into_the_loadout(self):
        brain = brains.Notes()
        brain.ask = Mock(return_value={"seeds": ["peashooter"], "plan": "my choice"})
        result = brain.pick_seeds([{"name": "puff_shroom", "cost": 0},
                                   {"name": "peashooter", "cost": 100}], 1, {})
        self.assertEqual(result["seeds"], ["peashooter"])

    def test_reflection_gets_cost_facts_but_existing_notebook_is_not_edited_when_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            journal.data["lessons"] = ["my old unsupported hypothesis"]
            journal.save()
            before = journal.path.read_bytes()
            self.assertIn("strategy hypotheses", journal.prompt_block())
            self.assertEqual(journal.path.read_bytes(), before)
            brain = Mock()
            brain.plan_effort = None
            brain.ask.return_value = {"summary": "my summary", "general_lessons": journal.lessons,
                                     "situation_lessons": []}
            journal.reflect(brain, "4-1", "lost", "some plants died", "fog")
            prompt = brain.ask.call_args.args[1]
            self.assertIn('"puff_shroom": 0', prompt)
            self.assertIn('"sea_shroom": 0', prompt)
            self.assertIn("do not infer zero contribution from disappearance", prompt)
            self.assertEqual(journal.lessons, ["my old unsupported hypothesis"])
            saved = json.loads(journal.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["history"][-1]["verified_packet_costs"]["puff_shroom"], 0)


if __name__ == "__main__":
    unittest.main()
