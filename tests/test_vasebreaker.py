"""Vase visibility, temporary resources, and mode-specific observation regressions."""
import struct
import unittest
from unittest.mock import Mock

from pvz import agent
from pvz.player import brains
from pvz.game import offsets as O
from pvz.game import vasebreaker
from pvz.game.state import GameReader
from tests.test_campaign import board, operator, seed


def vase_board():
    state = board("night", "vases")
    state["level"], state["sun"] = 35, 0
    state["items"] = [{"type": "vase", "row": 0, "col": 8, "appearance": "plain"}]
    return state


def packet(state, name="peashooter", ident="0:65536", **fields):
    item = seed(state, name)
    item.update(slot=None, packet_id=ident, pickup=(600, 200), age_seconds=1.0,
                expires_in=14.0, flashing=False, fading=False)
    item.update(fields)
    return item


class ReaderTests(unittest.TestCase):
    def test_visible_sprite_does_not_disclose_concealed_content(self):
        reader = GameReader.__new__(GameReader)
        raw = bytearray(O.GRID_ITEM_SIZE * 4)
        for index, appearance in enumerate((3, 4, 5, 99)):
            base = index * O.GRID_ITEM_SIZE
            struct.pack_into("<i", raw, base + O.GI_TYPE, 7)
            struct.pack_into("<i", raw, base + O.GI_STATE, appearance)
            struct.pack_into("<2i", raw, base + O.GI_COL, index, 0)
            # Deliberately conflicting hidden contents: never used to identify a vase.
            struct.pack_into("<3i", raw, base + 0x3C, 23, 7, 1)
        reader._live_entries = Mock(return_value=[(raw, i * O.GRID_ITEM_SIZE) for i in range(4)])
        reader._block = Mock(return_value=bytes(24))
        items = reader.grid_items(100)
        self.assertEqual([i["appearance"] for i in items], ["plain", "plant", "zombie", "unknown"])
        self.assertTrue(all(set(i) == {"type", "row", "col", "appearance"} for i in items))
        for index in range(4):
            struct.pack_into("<3i", raw, index * O.GRID_ITEM_SIZE + 0x3C, 1, 0, 2)
        self.assertEqual(reader.grid_items(100), items)

    def test_packets_are_free_and_expiry_uses_ground_time_not_total_age(self):
        reader = GameReader.__new__(GameReader)
        raw = bytearray(O.COIN_SIZE * 2)
        for index, elapsed in enumerate((200, 1300)):
            base = index * O.COIN_SIZE
            struct.pack_into("<i", raw, base + O.CO_TYPE, O.USABLE_SEED_PACKET)
            struct.pack_into("<i", raw, base + O.CO_SEED, 5)
            struct.pack_into("<2f", raw, base + O.CO_X, 600, 200)
            struct.pack_into("<i", raw, base + O.CO_AGE, elapsed + 70)
            struct.pack_into("<i", raw, base + O.CO_DISAPPEAR, elapsed)
        reader._ptr = Mock(return_value=1000)
        reader._int = Mock(return_value=2)
        reader._block = Mock(return_value=raw)
        packets = reader.vase_seeds(100)
        self.assertEqual([s["expires_in"] for s in packets], [13.0, 2.0])
        self.assertEqual([s["age_seconds"] for s in packets], [2.7, 13.7])
        self.assertEqual([s["flashing"] for s in packets], [False, True])
        self.assertEqual(len({s["packet_id"] for s in packets}), 2)
        self.assertTrue(all(s["cost"] == 0 and s["ready"] and s["slot"] is None for s in packets))
        self.assertEqual(packets[0]["pickup"], (620, 230))

    def test_vases_do_not_read_a_missing_normal_seed_bank(self):
        reader = GameReader.__new__(GameReader)
        state = vase_board()
        reader.version = "test"
        reader.board = Mock(return_value=100)
        reader.level_info = Mock(return_value={k: state[k] for k in
                                               ("level", "terrain", "rows", "conveyor", "special")})
        for method, key in (("sun", "sun"), ("wave", "wave"), ("plants", "plants"),
                            ("zombies", "zombies"), ("mowers", "mowers"),
                            ("cell_types", "cells"), ("grid_items", "items")):
            setattr(reader, method, Mock(return_value=state[key]))
        reader.paused, reader.tutorial = Mock(return_value=False), Mock(return_value=0)
        reader.sun_drops, reader.awards = Mock(return_value=[]), Mock(return_value=[])
        reader.seeds = Mock(side_effect=AssertionError("no seed bank in this mode"))
        reader.vase_seeds = Mock(return_value=[])
        snapshot = reader.snapshot()
        self.assertNotIn("errors", snapshot)
        reader.seeds.assert_not_called()
        reader.vase_seeds.assert_called_once_with(100)


class PlayerInformationTests(unittest.TestCase):
    def test_prompt_explains_resources_and_spawn_location_without_strategy(self):
        state = vase_board()
        state["items"].append({"type": "vase", "row": 1, "col": 7, "appearance": "plant"})
        packet(state, expires_in=2.0, flashing=True)
        for compact in (False, True):
            text = brains.describe(state, [], compact=compact)
            self.assertIn("vase(plant)", text)
            self.assertIn("plain vase's contents are unknown", text)
            self.assertIn("at that vase's position", text)
            self.assertIn("peashooter: FREE, READY, expires in ~2.0s, FLASHING", text)
            self.assertIn("no scheduled waves or normal seed bank", text)
            self.assertIn("roughly 15 seconds after landing", text)
            self.assertIn("Row summary", text)
            self.assertNotIn("starting near the right edge", text)
            self.assertNotIn("Open one at a time", text)
            self.assertNotIn("Sun-only comparison", text)
            self.assertNotIn("Wave: 0/20", text)

    def test_green_vase_stays_a_blocked_cell_and_can_be_broken(self):
        state = vase_board()
        state["items"][0]["appearance"] = "plant"
        packet(state)
        self.assertEqual(agent.validate({"type": "plant", "seed": "peashooter", "row": 0, "col": 8}, state)[0], "reject")
        self.assertEqual(agent.validate({"type": "break_vase", "row": 0, "col": 8}, state)[0], "ok")


class ObservationTests(unittest.TestCase):
    def test_reveals_expiry_and_new_arrangements_are_recorded_once(self):
        observer = vasebreaker.Observer()
        state = vase_board()
        self.assertEqual(observer.observe(state), [])
        self.assertEqual(state["vase_stage"], 1)
        state["items"] = []
        item = packet(state)
        messages = observer.observe(state)
        self.assertTrue(any("vase at row 0 col 8 broke" in m for m in messages))
        self.assertTrue(any("free peashooter packet" in m and "appeared" in m for m in messages))
        self.assertEqual(observer.observe(state), [])
        item["flashing"] = True
        self.assertEqual(len(observer.observe(state)), 1)
        state["seeds"] = []
        messages = observer.observe(state)
        self.assertIn("cause not inferred", messages[0])
        state["items"] = [{"type": "vase", "row": 2, "col": 7}]
        self.assertIn("new vase arrangement", observer.observe(state)[0])
        self.assertEqual(state["vase_stage"], 2)

    def test_annotation_adds_observed_facts_to_reflection_evidence(self):
        op = operator()
        op.recorder = Mock(events=[])
        state = vase_board()
        op.annotate(state)
        state["items"] = []
        packet(state)
        op.annotate(state)
        self.assertTrue(any("vase at row" in m for m in op.recorder.events))
        self.assertTrue(any("packet" in m for m in op.recorder.events))

    def test_reveals_and_flashing_packets_wake_player_within_existing_rate_limit(self):
        state = vase_board()
        previous, old_observation = agent.decision_context(state), vasebreaker.context(state)
        state["items"] = []
        item = packet(state)
        options = dict(conveyor=True, queued=True, completed=False, fruitless=5,
                       previous_vase_observation=old_observation)
        self.assertIsNone(agent.decision_reason(agent.decision_context(state), previous, since=3,
                                                vase_observation=vasebreaker.context(state), **options))
        self.assertEqual(agent.decision_reason(agent.decision_context(state), previous, since=4,
                                                vase_observation=vasebreaker.context(state), **options), "vase_revealed")
        previous, old_observation = agent.decision_context(state), vasebreaker.context(state)
        item["flashing"] = True
        options["previous_vase_observation"] = old_observation
        self.assertEqual(agent.decision_reason(agent.decision_context(state), previous, since=4,
                                                vase_observation=vasebreaker.context(state), **options), "packet_expiring")
        options["previous_vase_observation"] = vasebreaker.context(state)
        state["items"] = [{"type": "vase", "row": 2, "col": 7}]
        self.assertEqual(agent.decision_reason(agent.decision_context(state), previous, since=4,
                                                vase_observation=vasebreaker.context(state), **options), "vase_arrangement_changed")


if __name__ == "__main__":
    unittest.main()
