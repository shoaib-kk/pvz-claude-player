"""Offline regression tests. Uses synthetic boards and mocked readers only."""

import copy
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agent
import brains
import offsets as O
from controller import Controller
from state import GameReader


def board(terrain="day", special=None):
    rows = 6 if terrain in ("pool", "fog") else 5
    cells = [[O.CELL_GRASS] * 9 for _ in range(rows)]
    if rows == 6:
        cells[2] = [O.CELL_POOL] * 9
        cells[3] = [O.CELL_POOL] * 9
    return {
        "in_level": True, "terrain": terrain, "special": special, "rows": rows,
        "conveyor": special in ("bowling", "boss"), "sun": 500, "wave": [0, 20],
        "grid": [[None] * 9 for _ in range(rows)], "cells": cells, "items": [],
        "plants": [], "zombies": [], "mowers": [True] * rows, "seeds": [],
    }


def seed(state, name, ready=True, cost=0):
    item = {"name": name, "slot": len(state["seeds"]), "ready": ready, "cost": cost}
    state["seeds"].append(item)
    return item


def plant(state, name, row, col, asleep=False):
    state["plants"].append({"type": name, "row": row, "col": col, "hp": 300, "asleep": asleep})
    if name not in ("lily_pad", "flower_pot", "pumpkin"):
        state["grid"][row][col] = name


def action(name, row, col):
    return {"type": "plant", "seed": name, "row": row, "col": col}


def operator():
    op = agent.Agent.__new__(agent.Agent)
    op.log = Mock()
    op.show = Mock()
    op.capture_result = Mock()
    op.ctl = Mock()
    op.reader = Mock()
    op.reset_plan()
    op.board_at_start = 100
    op.decisions = 0
    op.levels = 1
    op.until_level = 50
    op.retries = 0
    op.auto_sun = False
    op.max_decisions = None
    return op


class ValidationTests(unittest.TestCase):
    def test_pool_sixth_row_and_water_support(self):
        state = board("pool")
        seed(state, "peashooter")
        self.assertEqual(agent.validate(action("peashooter", 5, 0), state)[0], "ok")
        self.assertEqual(agent.validate(action("peashooter", 2, 0), state)[0], "reject")
        seed(state, "lily_pad")
        self.assertEqual(agent.validate(action("lily_pad", 2, 0), state)[0], "ok")
        plant(state, "lily_pad", 2, 0)
        self.assertEqual(agent.validate(action("peashooter", 2, 0), state)[0], "ok")
        self.assertEqual(agent.validate(action("lily_pad", 2, 0), state)[0], "reject")
        self.assertEqual(agent.validate(action("lily_pad", 0, 0), state)[0], "reject")

    def test_roof_layers_and_cattail(self):
        state = board("roof")
        seed(state, "cabbage_pult")
        seed(state, "flower_pot")
        self.assertEqual(agent.validate(action("cabbage_pult", 0, 0), state)[0], "reject")
        self.assertEqual(agent.validate(action("flower_pot", 0, 0), state)[0], "ok")
        plant(state, "flower_pot", 0, 0)
        self.assertEqual(agent.validate(action("cabbage_pult", 0, 0), state)[0], "ok")
        water = board("pool")
        seed(water, "cattail")
        self.assertEqual(agent.validate(action("cattail", 2, 0), water)[0], "reject")
        plant(water, "lily_pad", 2, 0)
        self.assertEqual(agent.validate(action("cattail", 2, 0), water)[0], "ok")
        plant(water, "peashooter", 2, 0)
        self.assertEqual(agent.validate(action("cattail", 2, 0), water)[0], "reject")

    def test_graves_craters_sleeping_and_pumpkins(self):
        state = board("night")
        seed(state, "grave_buster")
        seed(state, "peashooter")
        state["items"] = [{"type": "grave", "row": 0, "col": 4}]
        self.assertEqual(agent.validate(action("grave_buster", 0, 4), state)[0], "ok")
        self.assertEqual(agent.validate(action("peashooter", 0, 4), state)[0], "reject")
        state["items"][0]["type"] = "crater"
        self.assertEqual(agent.validate(action("grave_buster", 0, 4), state)[0], "reject")
        seed(state, "coffee_bean")
        plant(state, "puff_shroom", 0, 0, asleep=True)
        self.assertEqual(agent.validate(action("coffee_bean", 0, 0), state)[0], "ok")
        state["plants"][0]["asleep"] = False
        self.assertEqual(agent.validate(action("coffee_bean", 0, 0), state)[0], "reject")
        seed(state, "pumpkin")
        self.assertEqual(agent.validate(action("pumpkin", 0, 0), state)[0], "ok")
        plant(state, "pumpkin", 0, 0)
        self.assertEqual(agent.validate(action("pumpkin", 0, 0), state)[0], "reject")

    def test_bowling_duplicate_cards_and_vases(self):
        state = board(special="bowling")
        seed(state, "wall_nut", ready=False)
        chosen = seed(state, "wall_nut")
        self.assertIs(agent.validate(action("wall_nut", 0, 0), state)[2], chosen)
        self.assertEqual(agent.validate(action("wall_nut", 0, 3), state)[0], "reject")
        seed(state, "peashooter")
        self.assertEqual(agent.validate(action("peashooter", 0, 0), state)[0], "reject")
        vases = board(special="vases")
        vases["items"] = [{"type": "vase", "row": 0, "col": 8}]
        smash = {"type": "break_vase", "row": 0, "col": 8}
        self.assertEqual(agent.validate(smash, vases)[0], "ok")
        vases["items"] = []
        self.assertEqual(agent.validate(smash, vases)[0], "reject")

    def test_boss_last_column_and_sun_wait(self):
        state = board("boss", "boss")
        seed(state, "jalapeno")
        plant(state, "flower_pot", 0, 8)
        self.assertEqual(agent.validate(action("jalapeno", 0, 8), state)[0], "reject")
        normal = board()
        normal["sun"] = 75
        seed(normal, "peashooter", cost=100)
        self.assertEqual(agent.validate(action("peashooter", 0, 0), normal)[0], "later")

    def test_old_logged_boards_still_work(self):
        state = board()
        for key in ("terrain", "special", "rows", "conveyor", "items"):
            state.pop(key)
        seed(state, "sunflower", cost=50)
        self.assertEqual(agent.validate(action("sunflower", 0, 0), state)[0], "ok")
        self.assertIn("row 4", brains.describe(state, []))


class GeometryAndReaderTests(unittest.TestCase):
    def test_shovel_stays_at_top_when_seed_bank_is_above_window(self):
        ctl = Controller.__new__(Controller)
        ctl._bank = Mock(return_value=(1000, 0, -87, 599))
        self.assertEqual(ctl.shovel_center(), (634, 38))
        ctl.hover = Mock()
        with self.assertRaises(ValueError):
            ctl.click(634, -49)
        ctl.hover.assert_not_called()

    def test_live_sun_pickup_does_not_need_an_array_id_tail(self):
        reader = GameReader.__new__(GameReader)
        raw = bytearray(O.COIN_SIZE)
        struct.pack_into("<i", raw, O.CO_TYPE, 4)
        struct.pack_into("<2f", raw, O.CO_X, 300, 200)
        reader._ptr = Mock(return_value=1000)
        reader._int = Mock(return_value=1)
        reader._block = Mock(return_value=raw)
        self.assertEqual(reader.coins(100), [{"x": 330, "y": 230, "type": 4}])

    def test_saved_game_dialog_is_distinct_from_pause(self):
        from PIL import Image
        ctl = Controller.__new__(Controller)
        ctl.to_screen = Mock(return_value=(0, 0))
        image = Image.new("RGB", (800, 600), (20, 130, 20))
        for point in ((160, 260), (200, 360), (360, 360), (400, 405)):
            image.putpixel(point, (85, 87, 117))
        with patch("controller.pyautogui.screenshot", return_value=image):
            self.assertEqual(ctl.dialog_kind(), "continue")
        image = Image.new("RGB", (800, 600), (20, 130, 20))
        for point in ctl.DIALOG_POINTS:
            image.putpixel(point, (30, 30, 45))
        with patch("controller.pyautogui.screenshot", return_value=image):
            self.assertEqual(ctl.dialog_kind(), "pause")

    def test_chooser_layout_uses_seed_positions_for_both_widget_layouts(self):
        reader = GameReader.__new__(GameReader)
        reader._ptr = Mock(side_effect=[10, 1000])
        def read_int(address):
            relative = address - 1000 - 0xBC
            index, offset = divmod(relative, 0x3C)
            if not 0 <= index < 48:
                return -1
            return {0: 22 + 53 * (index % 8), 4: 128 + 73 * (index // 8),
                    0x20: index}.get(offset, -1)
        reader._int = Mock(side_effect=read_int)
        self.assertEqual(reader.chooser_layout(), (163, 73))

    def test_chooser_waits_for_hidden_bank_before_reading_cards(self):
        import seed_select
        ctl = Mock()
        ctl.seed_center.side_effect = [(110, -44), (110, 10), (110, 43)]
        with patch("seed_select.in_chooser", return_value=True), patch("seed_select.time.sleep"):
            seed_select.wait_for_bank(ctl)
        self.assertEqual(ctl.seed_center.call_count, 3)

    def test_pool_and_roof_geometry(self):
        self.assertEqual(Controller.cell_center(0, 0), (80, 130))
        self.assertEqual(Controller.cell_center(5, 8, "pool"), (720, 547))
        self.assertEqual(Controller.cell_center(0, 0, "roof"), (80, 212))
        self.assertEqual(Controller.cell_center(0, 5, "roof"), (480, 112))
        with self.assertRaises(ValueError):
            Controller.cell_center(5, 0)

    def test_level_metadata_for_every_adventure_level(self):
        reader = GameReader.__new__(GameReader)
        reader.mode = Mock(return_value=0)
        for level in range(1, 51):
            background = (level - 1) // 10 if level != 50 else 5
            reader._int = Mock(side_effect=[background, level])
            info = reader.level_info(100)
            self.assertEqual(info["level"], level)
            self.assertEqual(info["conveyor"], level in O.ADVENTURE_CONVEYORS)
            self.assertEqual(info["rows"], 6 if 21 <= level <= 40 else 5)
            self.assertEqual(info["special"], O.ADVENTURE_SPECIALS.get(level))

    def test_snapshot_keeps_all_six_rows(self):
        reader = GameReader.__new__(GameReader)
        reader.version = "fake"
        reader.board = Mock(return_value=100)
        reader.level_info = Mock(return_value={"rows": 6, "terrain": "pool", "special": None,
                                                "level": 21, "conveyor": False})
        for name, value in {
            "sun": 50, "wave": [1, 20], "paused": False, "tutorial": 0, "seeds": [],
            "plants": [{"type": "peashooter", "row": 5, "col": 1}],
            "zombies": [], "mowers": [True] * 6, "sun_drops": [], "awards": [],
            "cell_types": [[1] * 9 for _ in range(6)], "grid_items": [],
        }.items():
            setattr(reader, name, Mock(return_value=value))
        snap = reader.snapshot()
        self.assertEqual(snap["grid"][5][1], "peashooter")
        reader.cell_types.assert_called_once_with(100, 6)
        reader.mowers.assert_called_once_with(100, 6)

    def test_conveyor_seeds_ignore_empty_slots_and_costs(self):
        reader = GameReader.__new__(GameReader)
        bank = 1000
        reader._ptr = Mock(return_value=bank)
        ints = {bank + O.SB_COUNT: 3, bank + O.OBJ_X: 0}
        for slot, kind in enumerate((3, -1, 49)):
            base = bank + O.SB_FIRST_CARD + slot * O.CARD_SIZE
            ints.update({base + O.C_TYPE: kind, base + O.OBJ_X: 90 + 50 * slot,
                         base + O.C_OFFSET_X: 400, base + O.OBJ_W: 50,
                         base + O.C_RECHARGE_NOW: 0, base + O.C_RECHARGE_MAX: 0})
        reader._int = Mock(side_effect=lambda addr: ints[addr])
        reader.pm = SimpleNamespace(read_bool=Mock(return_value=True))
        cards = reader.seeds(10, conveyor=True)
        self.assertEqual([(s["slot"], s["name"], s["cost"]) for s in cards],
                         [(0, "wall_nut", 0), (2, "explode_o_nut", 0)])

    def test_grids_item_memory_parser(self):
        reader = GameReader.__new__(GameReader)
        raw = bytearray(O.GRID_ITEM_SIZE)
        struct.pack_into("<i", raw, O.GI_TYPE, 1)
        struct.pack_into("<2i", raw, O.GI_COL, 8, 5)
        reader._live_entries = Mock(return_value=[(raw, 0)])
        reader._block = Mock(return_value=bytes(24))
        self.assertEqual(reader.grid_items(100), [{"type": "grave", "row": 5, "col": 8}])

    def test_zomboni_ice_blocks_planting(self):
        reader = GameReader.__new__(GameReader)
        reader._live_entries = Mock(return_value=[])
        reader._block = Mock(side_effect=[
            struct.pack("<6i", 800, 800, 400, 800, 800, 800),
            struct.pack("<6i", 0, 0, 50, 0, 0, 0),
        ])
        state = board("pool")
        state["items"] = reader.grid_items(100)
        seed(state, "lily_pad")
        self.assertEqual(agent.validate(action("lily_pad", 2, 4), state)[0], "reject")
        self.assertEqual(agent.validate(action("lily_pad", 2, 3), state)[0], "ok")

    def test_prompt_keeps_supports_and_special_rules(self):
        state = board("fog")
        plant(state, "lily_pad", 2, 0)
        plant(state, "pumpkin", 2, 0)
        plant(state, "sun_shroom", 2, 0, asleep=True)
        prompt = brains.describe(state, [])
        self.assertIn("row 5", prompt)
        self.assertIn("lily_pad+pumpkin+sun_shroom(asleep)", prompt)
        self.assertIn("no falling sun", prompt)
        self.assertIn("Terrain: roof", brains.pick_prompt([], 0, {}, terrain="roof"))


class LoopTests(unittest.TestCase):
    def test_absolute_endpoint_stops_after_level_ten(self):
        op = operator()
        op.levels = 50
        op.until_level = 10
        op.get_to_playing = Mock(return_value=True)
        op.reader.level_info.side_effect = [
            {"level": 9, "special": None, "terrain": "day"},
            {"level": 10, "special": None, "terrain": "day"},
        ]
        op.play = Mock(return_value="won")
        self.assertEqual(op.play_levels(), ("won", 2))
        self.assertEqual(op.play.call_count, 2)

    @patch("agent.time.sleep")
    def test_navigation_handles_loading_award_menu_and_intro(self, _):
        for start, expected in (
            ("loading", (400, 558)),
            ("award", (402, 520)),
            ("menu", (565, 130)),
            ("zombies_won", (395, 366)),
        ):
            op = operator()
            op.reader.scene.side_effect = [start, "playing"]
            op.reader.board.return_value = 0
            self.assertTrue(op.get_to_playing(retry=True))
            op.ctl.click.assert_called_once_with(*expected)
        op = operator()
        op.reader.scene.side_effect = ["intro", "playing"]
        op.reader.board.return_value = 100
        op.reader.mode.return_value = 0
        op.reader.tutorial.return_value = 0
        op.reader.dave_talking.return_value = True
        self.assertTrue(op.get_to_playing())
        op.ctl.click.assert_called_once_with(430, 120)

    @patch("agent.time.sleep")
    def test_navigation_handles_chooser_without_starting_a_game(self, _):
        op = operator()
        op.reader.scene.side_effect = ["intro", "playing"]
        op.reader.board.return_value = 100
        op.reader.mode.return_value = 0
        op.reader.tutorial.return_value = 0
        op.reader.dave_talking.return_value = False
        op.choose_plants = Mock()
        with patch("seed_select.in_chooser", return_value=True):
            self.assertTrue(op.get_to_playing())
        op.choose_plants.assert_called_once()

    @patch("agent.time.sleep")
    def test_almanac_shop_and_zen_transition_actions(self, _):
        for previous, expected in ((14, (720, 580)), (24, (430, 553))):
            op = operator()
            op.reader.scene.side_effect = ["award", "award", "playing"]
            op.reader.board.return_value = 0
            op.reader.dave_talking.return_value = False
            with patch("agent.time.monotonic", side_effect=range(0, 100, 2)):
                with patch("agent.pyautogui.press"):
                    self.assertTrue(op.get_to_playing(previous_level=previous))
            self.assertIn(unittest.mock.call(*expected), op.ctl.click.call_args_list)
        op = operator()
        op.reader.scene.side_effect = ["playing", "playing"]
        op.reader.board.return_value = 100
        op.reader.mode.side_effect = [43, 0]
        op.reader.tutorial.return_value = 27
        self.assertTrue(op.get_to_playing(previous_level=44))
        op.ctl.click.assert_called_once_with(740, 12)

    @patch("agent.time.sleep")
    def test_navigation_timeout_and_credits_stop(self, _):
        op = operator()
        op.reader.scene.return_value = "intro"
        op.reader.board.return_value = 0
        op.reader.dave_talking.return_value = False
        with patch("agent.time.monotonic", side_effect=range(20)):
            with patch("seed_select.in_chooser", return_value=False):
                self.assertFalse(op.get_to_playing(timeout=2))
        op.reader.scene.return_value = "credits"
        self.assertFalse(op.get_to_playing())

    @patch("agent.time.sleep")
    def test_target_confirmation_survives_unrelated_plant_loss(self, _):
        state = board()
        chosen = seed(state, "peashooter")
        plant(state, "sunflower", 1, 0)
        after = copy.deepcopy(state)
        after["plants"] = []
        plant(after, "peashooter", 0, 0)
        op = operator()
        op.reader.scene.return_value = "playing"
        op.reader.board.return_value = 100
        op.snapshot = Mock(return_value=after)
        self.assertTrue(op.perform(action("peashooter", 0, 0), chosen, state))
        op.ctl.plant.assert_called_once()

    @patch("agent.time.sleep")
    def test_consumed_conveyor_instant_counts_as_success(self, _):
        state = board(special="bowling")
        chosen = seed(state, "wall_nut")
        after = copy.deepcopy(state)
        after["seeds"] = []
        op = operator()
        op.reader.scene.return_value = "playing"
        op.reader.board.return_value = 100
        op.snapshot = Mock(return_value=after)
        self.assertTrue(op.perform(action("wall_nut", 0, 0), chosen, state))

    @patch("agent.time.sleep")
    def test_play_waits_for_reward_scene(self, _):
        state = board()
        state["awards"] = [{"x": 400, "y": 300, "type": 7}]
        op = operator()
        op.reader.board.return_value = 100
        op.reader.scene.side_effect = ["playing", "award", "award"]
        op.reader.level_info.return_value = {"level": 3}
        op.ensure_focus = Mock()
        op.snapshot = Mock(return_value=state)
        self.assertEqual(op.play(), "won")
        op.ctl.click.assert_called_once_with(400, 300)
        self.assertEqual(op.decisions, 0)

    @patch("agent.time.sleep")
    def test_reward_animation_does_not_start_new_gameplay(self, _):
        state = board()
        state["awards"] = [{"x": 400, "y": 300, "type": 7}]
        after = copy.deepcopy(state)
        after["awards"] = []
        op = operator()
        op.reader.board.return_value = 100
        op.reader.scene.side_effect = ["playing", "playing", "award", "award"]
        op.reader.level_info.return_value = {"level": 3}
        op.ensure_focus = Mock()
        op.snapshot = Mock(side_effect=[state, after])
        op.work_queue = Mock()
        self.assertEqual(op.play(), "won")
        op.work_queue.assert_not_called()

    @patch("agent.time.sleep")
    def test_manual_menu_is_not_a_win(self, _):
        op = operator()
        op.reader.board.return_value = 100
        op.reader.scene.return_value = "menu"
        op.reader.level_info.return_value = {"level": 3}
        self.assertEqual(op.play(), "left")

    def test_campaign_retries_and_resets_plan(self):
        op = operator()
        op.levels = 2
        op.retries = 1
        op.get_to_playing = Mock(return_value=True)
        op.reader.board.return_value = 100
        op.reader.level_info.side_effect = [
            {"level": 3, "special": None, "terrain": "day"},
            {"level": 3, "special": None, "terrain": "day"},
            {"level": 4, "special": None, "terrain": "day"},
        ]
        def play():
            self.assertEqual(op.queue, [])
            op.queue.append(action("peashooter", 0, 0))
            return next(results)
        results = iter(["lost", "won", "won"])
        op.play = play
        self.assertEqual(op.play_levels(), ("won", 2))

    def test_restart_may_press_try_again_on_the_game_over_screen(self):
        op = operator()
        op.restart = True
        op.get_to_playing = Mock(return_value=False)
        op.play_levels()
        self.assertTrue(op.get_to_playing.call_args.kwargs["retry"])
        op.restart = False
        op.play_levels()
        self.assertFalse(op.get_to_playing.call_args.kwargs["retry"])

    def test_attempt_limit_counts_wins_and_retries_before_next_navigation(self):
        op = operator()
        op.levels = 50
        op.retries = 2
        op.max_attempts = 3
        op.get_to_playing = Mock(return_value=True)
        op.reader.level_info.side_effect = [
            {"level": n, "special": None, "terrain": "roof"} for n in (42, 43, 43)
        ]
        op.play = Mock(side_effect=["won", "lost", "won"])
        self.assertEqual(op.play_levels(), ("max_attempts", 2))
        self.assertEqual(op.play.call_count, 3)
        self.assertEqual(op.get_to_playing.call_count, 3)

    def test_three_losses_do_not_start_a_fourth_attempt(self):
        op = operator()
        op.levels = 50
        op.retries = 2
        op.max_attempts = 3
        op.get_to_playing = Mock(return_value=True)
        op.reader.level_info.return_value = {"level": 42, "special": None, "terrain": "roof"}
        op.play = Mock(return_value="lost")
        self.assertEqual(op.play_levels(), ("lost", 0))
        self.assertEqual(op.get_to_playing.call_count, 3)

    def test_campaign_stops_at_boss_or_exhausted_retries(self):
        op = operator()
        op.levels = 50
        op.get_to_playing = Mock(return_value=True)
        op.reader.level_info.return_value = {"level": 50, "special": "boss", "terrain": "boss"}
        op.play = Mock(return_value="won")
        self.assertEqual(op.play_levels(), ("won", 1))
        op.reader.level_info.return_value = {"level": 3, "special": None, "terrain": "day"}
        op.play.return_value = "lost"
        self.assertEqual(op.play_levels(), ("lost", 0))

    def test_whack_uses_no_model_request(self):
        op = operator()
        state = board("night", "whack")
        state["zombies"] = [{"x": 300, "row": 2, "type": "zombie"}]
        op.ctl.cell_center = Controller.cell_center
        self.assertTrue(op.special_controls(state))
        op.ctl.click.assert_called_once_with(350, 330)

    def test_boss_counter_uses_correct_instant(self):
        for kind, expected in (("fire", "ice_shroom"), ("ice", "jalapeno")):
            op = operator()
            state = board("boss", "boss")
            seed(state, expected)
            plant(state, "flower_pot", 2, 0)
            state["zombies"] = [{"type": "dr_zomboss", "projectile": {"id": 10, "row": 2, "type": kind}}]
            op.perform = Mock(return_value=True)
            self.assertTrue(op.special_controls(state))
            self.assertEqual(op.perform.call_args.args[0]["seed"], expected)
            self.assertEqual(op.perform.call_args.args[0]["row"], 2)
            self.assertFalse(op.special_controls(state))


if __name__ == "__main__":
    unittest.main()
