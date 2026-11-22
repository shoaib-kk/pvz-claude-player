"""Offline tests for staged plant knowledge, the lessons journal, and the coaching-free prompts."""
import copy
import tempfile
import unittest

import brains
import plant_info
from journal import MAX_LESSONS, Journal, LevelRecorder
from test_campaign import board, plant, seed


class PromptTests(unittest.TestCase):
    def test_compact_prompt_preserves_pending_moves_and_recharge(self):
        state = board()
        seed(state, "potato_mine", ready=False)["recharge"] = [1000, 3000]
        queued = [{"type": "plant", "seed": "potato_mine", "row": 4, "col": 0}]
        short = brains.describe(state, [], queued, compact=True)
        self.assertLess(len(short), len(brains.describe(state, [], queued)))
        self.assertIn("plant potato_mine at (4,0)", short)
        self.assertIn("ready in 20s", short)

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

    def test_chooser_knows_mushrooms_are_awake_in_fog(self):
        self.assertIn("Night and fog levels take place at night: there is no\nfalling sun and mushrooms are awake",
                      brains.PICK_SYSTEM)

    def test_pick_remembers_the_options_offered(self):
        brain = brains.Notes()
        brain.ask = lambda *a, **k: {"seeds": ["sun_shroom"], "plan": "p", "reasoning": "r"}
        brain.pick_seeds([{"name": "sun_shroom", "cost": 25}, {"name": "puff_shroom", "cost": 0}], 1, {})
        self.assertEqual(brain.last_options, ["sun_shroom", "puff_shroom"])

    def test_shooting_direction_is_a_stated_rule(self):
        self.assertIn("fire toward the street (higher columns) only", brains.SYSTEM_PROMPT)

    def test_row_summary_counts_direction_without_claiming_reach(self):
        s = board()
        plant(s, "peashooter", 4, 1)
        plant(s, "peashooter", 4, 7)            # behind the zombie at col 4
        s["zombies"] = [{"type": "conehead", "row": 4, "x": 380, "hp": 270, "armor_hp": 370}]
        out = brains.describe(s, [], compact=True)
        self.assertIn("row 4: 2 attackers (1 with the closest zombie in their firing direction)", out)
        self.assertIn("firing direction does not establish reach", out)
        self.assertNotIn("can hit the closest zombie", out)

    def test_roof_obstruction_is_known_before_picking_and_during_play(self):
        for terrain in ("roof", "boss"):
            with self.subTest(terrain=terrain):
                s = board(terrain)
                plant(s, "peashooter", 0, 1)
                s["zombies"] = [{"type": "zombie", "row": 0, "x": 650, "hp": 270, "armor_hp": 0}]
                pick = brains.pick_prompt([], 0, {}, terrain=terrain)
                play = brains.describe(s, [], compact=True)
                for text in (pick, play):
                    self.assertIn("A peashooter on the slope therefore cannot cover the whole row", text)
                    self.assertIn("Lobbed projectiles clear the roof slope", text)
                self.assertNotIn("can hit the closest zombie", play)
        self.assertNotIn(brains.ROOF_RULES, brains.pick_prompt([], 0, {}, terrain="day"))

    def test_zombies_are_drawn_in_the_lawn_grid(self):
        s = board()
        s["zombies"] = [{"type": "conehead", "row": 4, "x": 380, "hp": 270, "armor_hp": 370},
                        {"type": "zombie", "row": 0, "x": 760, "hp": 270, "armor_hp": 0}]
        out = brains.describe(s, [], compact=True)
        self.assertIn("row 4 M: .|.|.|.|. Z:conehead|.|.|.|.", out)
        self.assertIn("row 0 M: .|.|.|.|.|.|.|.|.  >> zombie", out)

    def test_shot_behind_zombies(self):
        s = board()
        s["zombies"] = [{"type": "zombie", "row": 2, "x": 300, "hp": 270, "armor_hp": 0}]  # col 3
        self.assertTrue(brains.shot_behind_zombies(s, 2, 6, "peashooter"))
        self.assertFalse(brains.shot_behind_zombies(s, 2, 3, "peashooter"))   # same tile still hits
        self.assertFalse(brains.shot_behind_zombies(s, 2, 1, "peashooter"))
        self.assertFalse(brains.shot_behind_zombies(s, 2, 6, "split_pea"))    # shoots backward too
        self.assertFalse(brains.shot_behind_zombies(s, 2, 6, "wall_nut"))
        self.assertFalse(brains.shot_behind_zombies(s, 1, 6, "peashooter"))   # no zombie in row

    def test_agent_reports_a_shooter_planted_behind_the_zombies(self):
        from unittest.mock import patch
        from test_campaign import action, operator
        op = operator()
        s = board()
        seed(s, "peashooter")
        s["zombies"] = [{"type": "zombie", "row": 2, "x": 300, "hp": 270, "armor_hp": 0}]
        op.queue = [action("peashooter", 2, 6)]
        op.recent = []
        op.planted_since_ask = 0
        with patch.object(op, "snapshot", return_value=s), patch.object(op, "perform", return_value=True):
            op.work_queue()
        self.assertTrue(any("every current zombie in row 2 has already passed it toward the house" in r
                            for r in op.recent))

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

    def test_catapult_mechanics_reach_chooser_and_board_without_strategy(self):
        s = board("roof")
        s["level"] = 46
        s["zombies"] = [{"type": "catapult", "row": 1, "x": 650, "hp": 850, "armor_hp": 0}]
        texts = [brains.pick_prompt([], 0, {"catapult": 1}, terrain="roof", level=46),
                 brains.describe(s, [], compact=True)]
        for text in texts:
            with self.subTest(text=text[:40]):
                self.assertIn("leftmost eligible plant in its own row", text)
                self.assertIn("front walls do not intercept the balls", text)
                self.assertIn("crushes plants, including Wall-nuts", text)
                self.assertIn("Umbrella Leaf blocks the balls, not the vehicle", text)
                self.assertNotIn("Bring a", text)

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

    def test_lost_plants_show_their_sun_cost_and_placements_are_counted(self):
        def board(plants, seeds):
            return {"in_level": True, "wave": [3, 10], "zombies": [], "mowers": [1] * 6,
                    "seeds": [{"name": n, "cost": c} for n, c in seeds],
                    "plants": [{"row": r, "col": c, "type": t} for r, c, t in plants]}
        seeds = [("puff_shroom", 0), ("fume_shroom", 75)]
        rec = LevelRecorder("4-1", ["puff_shroom", "fume_shroom"])
        rec.observe(board([(0, 3, "puff_shroom"), (1, 2, "fume_shroom")], seeds))
        rec.observe(board([(1, 2, "fume_shroom")], seeds))
        rec.observe(board([(0, 3, "puff_shroom"), (1, 2, "fume_shroom")], seeds))
        report = rec.report()
        self.assertIn("puff_shroom x1 (0 sun each)", report)
        self.assertIn("Replacement value of disappeared plants: 0 (NOT cash spent", report)
        self.assertEqual(rec.facts()["plants_placed"], 3)
        self.assertEqual(rec.facts()["wave"], [3, 10])

    def test_reflection_sees_earlier_attempts_at_the_same_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            brain = FakeBrain(["l"])
            j.reflect(brain, "4-1", "lost", "r", facts={"loadout": ["puff_shroom"], "wave": [10, 10],
                                                        "plants_placed": 39, "sun_lost": 0})
            j.reflect(brain, "3-1", "won", "r", facts={"loadout": ["peashooter"], "wave": [10, 10]})
            j.reflect(brain, "4-1", "lost", "r")
            self.assertNotIn("earlier attempts", brain.prompts[0])
            self.assertIn("lost at wave 10 of 10; loadout puff_shroom; plants placed 39; "
                          "replacement value of disappeared plants 0 (not spending)", brain.prompts[2])
            self.assertNotIn("loadout peashooter", brain.prompts[2])

    def test_report_lists_plants_left_out_of_the_loadout(self):
        rec = LevelRecorder("4-1", ["sun_shroom", "lily_pad"], ["sun_shroom", "sea_shroom", "lily_pad", "tangle_kelp"])
        report = rec.report()
        self.assertIn("Plants you could have brought but didn't: sea_shroom, tangle_kelp", report)
        self.assertNotIn("could have brought", LevelRecorder("4-1", ["sun_shroom"]).report())

    def test_water_plants_say_they_need_no_lily_pad(self):
        self.assertIn("no Lily Pad needed", plant_info.describe_plants(["sea_shroom"], 31)[0])
        self.assertIn("Aquatic plants (lily_pad, sea_shroom, tangle_kelp...)\ngo directly on water",
                      brains.PICK_SYSTEM)

    def test_fog_section_starts_from_the_night_lessons_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            j.data["sections"] = {"night": ["sun_shrooms first"], "fog": ["old fog lesson"]}
            block = j.prompt_block("fog")
            self.assertIn("For fog levels:\n- sun_shrooms first\n- old fog lesson", block)
            j.data["sections"]["fog"] = ["learned in fog"]       # later reflections own the section
            j.save()
            again = Journal(tmp)
            self.assertIn("- learned in fog", again.prompt_block("fog"))
            self.assertNotIn("sun_shrooms first", again.prompt_block("fog"))
            self.assertEqual(again.data["seeded"], ["fog"])
            self.assertNotIn("sun_shrooms", again.prompt_block("pool"))

    def test_fog_section_waits_for_a_night_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(tmp)
            j.prompt_block("fog")
            self.assertNotIn("fog", j.data.get("seeded", []))   # nothing to copy yet; try again later
            j.data["sections"]["night"] = ["sun_shrooms first"]
            self.assertIn("sun_shrooms first", j.prompt_block("fog"))

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
        self.assertIn("cherry_bomb at row 1 col 4 is no longer observed", report)
        self.assertIn("activation or destruction unknown; effect unverified", report)
        self.assertIn("potato_mine at row 2 col 5 is gone (exploded, or eaten before it armed)", report)
        self.assertNotIn("destroyed by zombies", report)

    def test_distant_catapult_and_missing_squash_do_not_prove_squash_activated(self):
        r = LevelRecorder("5-6")
        s = board("roof")
        plant(s, "squash", 1, 1)
        s["plants"][-1]["hp"] = 75
        s["zombies"] = [{"type": "catapult", "row": 1, "x": 650, "hp": 730, "armor_hp": 0}]
        r.observe(s)
        later = copy.deepcopy(s)
        later["plants"] = []
        r.observe(later)
        r.observe(later)  # the same absence must not be counted twice
        report = r.report()
        self.assertIn("squash at row 1 col 1 is no longer observed", report)
        self.assertIn("activation or destruction unknown; effect unverified", report)
        self.assertEqual(r.one_use_disappeared, {"squash": 1})
        self.assertNotIn("squash", r.used_count)
        self.assertNotIn("squash", r.lost_count)
        self.assertNotIn("was used up", report)
        self.assertNotIn("One-use plants used:", report)


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

    def test_fixed_loadout_facts_move_to_the_system_prompt(self):
        b = brains.SimpleBrain()
        b.set_loadout(["puff_shroom"], 16)
        self.assertIn("puff_shroom: Free mushroom", b.system(brains.SYSTEM_PROMPT))
        s = board(terrain="night")
        s["level"] = 16
        seed(s, "puff_shroom")
        self.assertNotIn("puff_shroom: Free mushroom", brains.describe(s, [], None, b.known_plants))
        self.assertIn("puff_shroom: Free mushroom", brains.describe(s, []))
        b.set_loadout([], 20)                        # conveyor: facts stay on each board
        self.assertEqual(b.knowledge, "")

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


class DecisionSchedulingTests(unittest.TestCase):
    def test_failed_answer_keeps_live_queue(self):
        from test_campaign import operator

        op = operator()
        pending_move = {"type": "plant", "seed": "sunflower", "row": 0, "col": 0}
        op.queue = [pending_move]
        op.apply_decision({"_error": True, "_usage": {"usage": None}, "_think": 1, "_state": board()})
        self.assertEqual(op.queue, [pending_move])

    def test_waits_on_same_board_but_wakes_when_a_seed_becomes_affordable(self):
        from agent import decision_context, decision_reason

        state = board()
        seed(state, "sunflower", cost=50)
        seed(state, "peashooter", cost=100)
        state["sun"] = 50
        previous = decision_context(state)
        options = dict(conveyor=False, queued=False, completed=False, since=35, fruitless=0)
        self.assertIsNone(decision_reason(previous, previous, **options))
        state["sun"] = 100
        self.assertEqual(decision_reason(decision_context(state), previous, **options), "card_available")

    def test_new_threat_can_use_a_free_card_during_backoff(self):
        from agent import decision_context, decision_reason

        state = board()
        seed(state, "puff_shroom", cost=0)
        previous = decision_context(state)
        options = dict(conveyor=False, queued=False, completed=False, since=10, fruitless=3)
        self.assertIsNone(decision_reason(previous, previous, **options))
        state["zombies"] = [{"type": "conehead", "row": 0, "x": 190, "hp": 270, "armor_hp": 200}]
        self.assertEqual(decision_reason(decision_context(state), previous, **options), "threat_changed")

    def test_threat_changes_wait_ten_seconds_but_a_fired_mower_does_not(self):
        from agent import decision_context, decision_reason

        state = board()
        seed(state, "puff_shroom", cost=0)
        previous = decision_context(state)
        options = dict(conveyor=False, queued=True, completed=False, fruitless=0)
        state["zombies"] = [{"type": "zombie", "row": 1, "x": 500, "hp": 270, "armor_hp": 0}]
        now = decision_context(state)
        self.assertIsNone(decision_reason(now, previous, since=6, **options))
        self.assertEqual(decision_reason(now, previous, since=10, **options), "threat_changed")
        state["mowers"][1] = False
        self.assertEqual(decision_reason(decision_context(state), previous, since=5, **options), "threat_changed")

    def test_only_player_grouping_pairs_a_lily_pad_and_plant(self):
        from agent import validate
        from queueing import check_unit

        state = board("pool")
        seed(state, "lily_pad", cost=25)
        fume = seed(state, "fume_shroom", cost=75)
        queue = [{"type": "plant", "seed": "lily_pad", "row": 2, "col": 1},
                 {"type": "plant", "seed": "fume_shroom", "row": 2, "col": 1}]
        state["sun"] = 50
        self.assertEqual(check_unit(queue, state, validate)[0], "later")
        self.assertEqual(check_unit(queue[:1], state, validate)[0], "ok")  # no inferred pair
        state["sun"] = 100
        self.assertEqual(check_unit(queue, state, validate)[0], "ok")
        fume["ready"] = False
        self.assertEqual(check_unit(queue, state, validate)[0], "later")
        self.assertEqual(check_unit(queue[:1], state, validate)[0], "ok")

    def test_new_copy_of_a_conveyor_card_is_a_change(self):
        from agent import decision_context, decision_reason

        state = board()
        seed(state, "wall_nut", cost=0)
        previous = decision_context(state)
        seed(state, "wall_nut", cost=0)
        self.assertEqual(decision_reason(decision_context(state), previous, conveyor=True, queued=False,
                                         completed=False, since=8, fruitless=3), "card_available")



class RejectedPlanTests(unittest.TestCase):
    def test_fully_rejected_plan_is_retried_soon_but_not_in_a_loop(self):
        from agent import decision_context, decision_reason
        state = board()
        seed(state, "peashooter", cost=100)
        ctx = decision_context(state)
        base = dict(conveyor=False, queued=False, completed=False)
        self.assertIsNone(decision_reason(ctx, ctx, since=8, fruitless=0, **base))
        self.assertEqual(decision_reason(ctx, ctx, since=8, fruitless=0, rejected=True, **base), "plan_rejected")
        self.assertIsNone(decision_reason(ctx, ctx, since=6, fruitless=0, rejected=True, **base))
        self.assertIsNone(decision_reason(ctx, ctx, since=8, fruitless=3, rejected=True, **base))


class PoolRuleTests(unittest.TestCase):
    def test_water_messages_and_mines(self):
        import agent
        s = board(terrain="pool")
        seed(s, "peashooter")
        seed(s, "potato_mine")
        status, reason, _ = agent.validate({"type": "plant", "seed": "peashooter", "row": 2, "col": 3}, s)
        self.assertEqual(status, "reject")
        self.assertIn("plant lily_pad at (2,3) first, then peashooter at (2,3)", reason)
        plant(s, "lily_pad", 2, 3)
        status, reason, _ = agent.validate({"type": "plant", "seed": "potato_mine", "row": 2, "col": 3}, s)
        self.assertEqual(status, "reject")
        self.assertIn("needs solid ground", reason)
        self.assertEqual(agent.validate({"type": "plant", "seed": "peashooter", "row": 2, "col": 3}, s)[0], "ok")


if __name__ == "__main__":
    unittest.main()
