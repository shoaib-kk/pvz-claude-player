"""Offline tests for staged plant knowledge, the lessons journal, and the coaching-free prompts."""
import copy
import tempfile
import unittest

import brains
import plant_info
from journal import MAX_LESSONS, Journal, LevelRecorder
from test_campaign import board, plant, seed


class PromptTests(unittest.TestCase):
    def test_no_hand_written_strategy(self):
        text = brains.SYSTEM_PROMPT + brains.PICK_SYSTEM
        for coaching in ("Wall-nut in col", "Sunflowers in cols", "6-8 Sunflowers", "UNDEFENDED",
                         "DANGER", "Bring a Lily Pad", "Prioritize"):
            self.assertNotIn(coaching, text)
        s = board()
        s["zombies"] = [{"type": "zombie", "row": 0, "x": 300, "hp": 270, "armor_hp": 0}]
        out = brains.describe(s, [])
        self.assertNotIn("UNDEFENDED", out)
        self.assertNotIn("DANGER", out)
        self.assertIn("row 0: 0 attackers", out)

    def test_plant_knowledge_is_staged_by_almanac_unlock(self):
        s = board(terrain="night")
        seed(s, "puff_shroom")
        s["level"] = 14                                  # 2-4: Almanac not unlocked yet
        before = brains.describe(s, [])
        self.assertIn("puff_shroom: Free mushroom that shoots short-range spores.", before)
        self.assertNotIn("Almanac", before)
        s["level"] = plant_info.ALMANAC_FROM_LEVEL       # 2-5
        after = brains.describe(s, [])
        self.assertIn("range only 3 tiles", after)
        self.assertIn("from your Almanac", after)

    def test_pick_prompt_lists_known_plants(self):
        text = brains.pick_prompt([{"name": "peashooter", "cost": 100}], 1, {}, level=3)
        self.assertIn("peashooter: Shoots peas", text)

    def test_every_plant_has_a_card(self):
        from state import PLANT_NAMES
        missing = [n for n in PLANT_NAMES if n not in plant_info.CARDS
                   and n not in ("imitater", "sprout", "leftpeater")]
        self.assertEqual(missing, [])

    def test_brain_system_prompt_includes_journal(self):
        b = brains.SimpleBrain()
        b.notes = "\n\nYour journal:\n- keep walls in range"
        self.assertTrue(b.system(brains.SYSTEM_PROMPT).endswith("keep walls in range"))


class ChooserWarningTests(unittest.TestCase):
    def test_detects_stone_warning_but_not_brown_chooser(self):
        from PIL import Image
        import seed_select
        stone = Image.new("RGB", (800, 600), (95, 97, 129))
        chooser = Image.new("RGB", (800, 600), (120, 80, 40))
        self.assertTrue(seed_select.warning_dialog(stone))
        self.assertFalse(seed_select.warning_dialog(chooser))


class FakeBrain:
    def __init__(self, lessons):
        self.lessons = lessons
        self.prompts = []

    def ask(self, system, user, schema):
        self.prompts.append(user)
        return {"summary": "Row 2 had no attackers.", "lessons": self.lessons}


class JournalTests(unittest.TestCase):
    def test_reflect_rewrites_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            self.assertIn("empty", j.prompt_block())
            brain = FakeBrain([f"lesson {i}" for i in range(20)])
            summary = j.reflect(brain, "1-7", "lost", "Timeline: ...")
            self.assertEqual(summary, "Row 2 had no attackers.")
            self.assertEqual(len(j.lessons), MAX_LESSONS)
            self.assertIn("(empty)", brain.prompts[0])
            again = Journal(tmp)                         # survives a restart
            self.assertEqual(again.lessons, j.lessons)
            self.assertIn("- lesson 0", again.prompt_block())
            brain2 = FakeBrain(["merged lesson"])
            again.reflect(brain2, "1-7", "won", "...")
            self.assertIn("- lesson 0", brain2.prompts[0])   # sees its old journal
            self.assertEqual(again.lessons, ["merged lesson"])
            md = (again.folder / "lessons.md").read_text(encoding="utf-8")
            self.assertIn("**1-7** (lost", md)
            self.assertIn("**1-7** (won", md)

    def test_brain_without_ask_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(Journal(tmp).reflect(object(), "1-1", "won", ""))


class RecorderTests(unittest.TestCase):
    def test_records_lost_plants_and_mowers(self):
        r = LevelRecorder("2-1", ["puff_shroom", "wall_nut"])
        s = board()
        s["wave"] = [3, 20]
        plant(s, "puff_shroom", 2, 1)
        plant(s, "wall_nut", 2, 5)
        r.observe(s)
        later = copy.deepcopy(s)
        later["wave"] = [4, 20]
        later["plants"] = [p for p in later["plants"] if p["type"] != "wall_nut"]
        later["mowers"][2] = False
        later["zombies"] = [{"type": "conehead", "row": 2, "x": 400, "hp": 270, "armor_hp": 300}]
        r.observe(later)
        report = r.report("BOARD")
        self.assertIn("Loadout: puff_shroom, wall_nut", report)
        self.assertIn("wave 4: lost wall_nut at row 2 col 5 (zombies in that row: conehead)", report)
        self.assertIn("wave 4: the lawn mower in row 2 fired; that row had 1 attackers and now has no mower", report)
        self.assertIn("Mowers left: 4", report)
        self.assertTrue(report.endswith("BOARD"))
        lost = r.report(outcome="lost")
        self.assertIn("How it ended: the zombie closest to the house was a conehead in row 2; "
                      "its mower had fired in wave 4, and the row had 1 attackers left.", lost)

    def test_mine_timing_is_reported(self):
        r = LevelRecorder("2-6")
        s = board()
        plant(s, "potato_mine", 1, 4)
        s["plants"][-1]["age"] = 6
        plant(s, "potato_mine", 2, 4)
        s["plants"][-1]["age"] = 30
        r.observe(s)
        later = copy.deepcopy(s)
        later["plants"] = []
        r.observe(later)
        report = r.report()
        self.assertIn("potato_mine at row 1 col 4 was eaten 6s after planting, before it armed", report)
        self.assertIn("potato_mine at row 2 col 4 exploded (30s after planting)", report)
        self.assertIn("Potato mines eaten before they armed: 1", report)

    def test_agent_reports_mine_and_mower_events_to_the_player(self):
        import agent
        from unittest.mock import Mock, patch
        op = agent.Agent.__new__(agent.Agent)
        op.log = Mock()
        op.reset_plan()
        s = board()
        plant(s, "potato_mine", 0, 4)
        with patch("agent.time.monotonic", return_value=100.0):
            op.annotate(s)
        later = copy.deepcopy(s)
        later["plants"] = []
        later["mowers"][3] = False
        with patch("agent.time.monotonic", return_value=105.0):
            op.annotate(later)
        self.assertIn("EVENT: your potato_mine at row 0 col 4 was eaten 5s after planting, before it armed",
                      op.recent)
        self.assertIn("EVENT: the lawn mower in row 3 fired; row 3 has no mower now", op.recent)
        self.assertIn("things that happened", brains.describe(later, op.recent))

    def test_end_of_level_mower_cash_in_is_not_an_event(self):
        import agent
        from unittest.mock import Mock
        op = agent.Agent.__new__(agent.Agent)
        op.log = Mock()
        op.ctl = Mock()
        op.reset_plan()
        s = board()
        op.annotate(s)
        s["awards"] = [{"type": 7, "x": 400, "y": 300}]
        self.assertTrue(op.click_reward(s))
        later = copy.deepcopy(s)
        later["mowers"] = [False] * 5
        op.annotate(later)
        self.assertFalse(any("lawn mower" in r for r in op.recent))

    def test_one_use_plants_are_not_losses(self):
        r = LevelRecorder("1-7")
        s = board()
        plant(s, "cherry_bomb", 1, 4)
        plant(s, "potato_mine", 2, 5)
        r.observe(s)
        later = copy.deepcopy(s)
        later["plants"] = []
        r.observe(later)
        report = r.report()
        self.assertIn("cherry_bomb at row 1 col 4 was used up", report)
        self.assertIn("potato_mine at row 2 col 5 is gone (exploded, or eaten before it armed)", report)
        self.assertNotIn("destroyed by zombies", report)


class PlanAndFactsTests(unittest.TestCase):
    def test_plan_is_written_at_pick_and_shown_every_decision(self):
        b = brains.SimpleBrain()
        calls = []

        def ask(system, user, schema, effort=None):
            calls.append((system, user, schema, effort))
            return {"reasoning": "r", "seeds": ["peashooter"], "plan": "Fume-shrooms in cols 3-4."}
        b.ask = ask
        b.plan_effort = "high"
        brains.Notes.pick_seeds(b, [{"name": "peashooter", "cost": 100}], 1, {"football": 2})
        self.assertEqual(b.plan, "Fume-shrooms in cols 3-4.")
        self.assertEqual(calls[0][3], "high")
        self.assertIn("plan", calls[0][2]["required"])
        self.assertIn("football: Wears football armour", calls[0][1])
        self.assertIn("Fume-shrooms in cols 3-4.", b.system(brains.SYSTEM_PROMPT))

    def test_board_shows_recharge_health_mines_zombies_and_sun_rate(self):
        s = board()
        s["level"] = 16
        s["sun_per_min"] = 75
        seed(s, "potato_mine", ready=False)["recharge"] = [1000, 3000]
        plant(s, "wall_nut", 1, 5)
        s["plants"][-1]["hp"] = 1000
        plant(s, "potato_mine", 2, 6)
        s["plants"][-1]["age"] = 4
        plant(s, "potato_mine", 3, 6)
        s["plants"][-1]["age"] = 20
        s["zombies"] = [{"type": "football", "row": 1, "x": 600, "hp": 270, "armor_hp": 1400}]
        out = brains.describe(s, [])
        self.assertIn("ready in 20s", out)
        self.assertIn("wall_nut(25%)", out)
        self.assertIn("potato_mine(arming 11s)", out)
        self.assertIn("potato_mine(armed)", out)
        self.assertIn("football: Wears football armour and moves fast. [Almanac: toughness ~84 peas", out)
        self.assertIn("Sun collected in the last minute: 75", out)
        s["level"] = 12
        self.assertNotIn("[Almanac", brains.describe(s, []))

    def test_agent_annotates_ages_and_sun_rate(self):
        import agent
        from unittest.mock import patch
        op = agent.Agent.__new__(agent.Agent)
        op.reset_plan()
        s = board()
        plant(s, "potato_mine", 0, 4)
        s["sun"] = 50
        with patch("agent.time.monotonic", return_value=100.0):
            op.annotate(s)
        later = copy.deepcopy(s)
        later["sun"] = 75
        with patch("agent.time.monotonic", return_value=112.0):
            op.annotate(later)
        self.assertEqual(later["plants"][0]["age"], 12.0)
        self.assertEqual(later["sun_per_min"], 25)


class JournalSectionTests(unittest.TestCase):
    def test_situation_sections(self):
        from journal import situation_of
        self.assertEqual(situation_of({"terrain": "night", "special": None, "conveyor": False}), "night")
        self.assertEqual(situation_of({"terrain": "day", "special": None, "conveyor": True}), "day conveyor")
        self.assertEqual(situation_of({"terrain": "day", "special": "bowling", "conveyor": True}), "bowling")
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)

            class B:
                plan_effort = "high"

                def __init__(self):
                    self.calls = []

                def ask(self, system, user, schema, effort=None):
                    self.calls.append((user, effort))
                    return {"summary": "s", "general_lessons": ["g1"], "situation_lessons": ["n1"]}
            b = B()
            j.reflect(b, "2-6", "lost", "timeline", "night", "my plan")
            self.assertEqual(b.calls[0][1], "high")
            self.assertIn("The plan you wrote before the level:\nmy plan", b.calls[0][0])
            self.assertEqual(j.lessons, ["g1"])
            self.assertEqual(j.section("night"), ["n1"])
            block = j.prompt_block("night")
            self.assertIn("General:\n- g1", block)
            self.assertIn("For night levels:\n- n1", block)
            self.assertNotIn("n1", j.prompt_block("pool"))
            md = (j.folder / "lessons.md").read_text(encoding="utf-8")
            self.assertIn("## Night levels", md)
            self.assertIn("Plan: my plan", md)


if __name__ == "__main__":
    unittest.main()
