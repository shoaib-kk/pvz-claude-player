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
        self.assertIn("wave 4: lawn mower used in row 2", report)
        self.assertIn("Mowers left: 4", report)
        self.assertTrue(report.endswith("BOARD"))

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


if __name__ == "__main__":
    unittest.main()
