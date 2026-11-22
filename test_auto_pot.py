import unittest
from unittest.mock import Mock
from execution import ExecutionTracker
from queueing import edit_queue, auto_pot, check_unit, units, repot
from placement import validate
from test_campaign import action, board, plant, seed


def roof(with_pot=True):
    s = board(terrain="roof")
    if with_pot:
        seed(s, "flower_pot", cost=25)
    seed(s, "peashooter", cost=100)
    seed(s, "potato_mine", cost=25)
    s["sun"] = 500
    return s


class AutoPotTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ExecutionTracker("t", Mock())

    def queue(self, s, actions, mode="replace", queue=()):
        return edit_queue(list(queue), {"edit": mode, "actions": actions}, self.tracker, 1, s)

    def test_unpotted_roof_plant_gets_pot_first_in_same_group(self):
        q = self.queue(roof(), [action("peashooter", 1, 2)])
        self.assertEqual([a["seed"] for a in q], ["flower_pot", "peashooter"])
        self.assertEqual(len(units(q)), 1)
        self.assertEqual(check_unit(units(q)[0], roof(), validate), ("ok", "ok"))

    def test_potted_cell_and_explicit_pot_are_left_alone(self):
        s = roof()
        plant(s, "flower_pot", 0, 0)
        q = self.queue(s, [action("peashooter", 0, 0), action("flower_pot", 1, 1), action("peashooter", 1, 1)])
        self.assertEqual([(a["seed"], a["row"]) for a in q],
                         [("peashooter", 0), ("flower_pot", 1), ("peashooter", 1)])

    def test_new_groups_do_not_collide_with_player_groups(self):
        a = dict(action("peashooter", 2, 2), group=1)
        out = auto_pot([action("peashooter", 1, 1), a], [], roof())
        self.assertEqual([x.get("group") for x in out], [2, 2, 1, 1])

    def test_not_applied_off_roof_without_pot_packet_or_for_ground_plants(self):
        day = board(); seed(day, "flower_pot"); seed(day, "peashooter")
        self.assertEqual(len(auto_pot([action("peashooter", 0, 0)], [], day)), 1)
        self.assertEqual(len(auto_pot([action("peashooter", 0, 0)], [], roof(with_pot=False))), 1)
        self.assertEqual(len(auto_pot([action("potato_mine", 0, 0)], [], roof())), 1)

    def test_pending_pot_in_append_mode_counts(self):
        q = self.queue(roof(), [action("flower_pot", 3, 3)])
        q = self.queue(roof(), [action("peashooter", 3, 3)], mode="append", queue=q)
        self.assertEqual([a["seed"] for a in q], ["flower_pot", "peashooter"])

    def test_eaten_pot_is_replaced_before_waiting_plant(self):
        s = roof()
        q = [dict(action("peashooter", 1, 1), id=1), dict(action("peashooter", 2, 2), id=2)]
        plant(s, "flower_pot", 2, 2)
        out = repot(q, s, lambda a: dict(a, id=9))
        self.assertEqual([(a["seed"], a["id"]) for a in out],
                         [("flower_pot", 9), ("peashooter", 1), ("peashooter", 2)])
        self.assertEqual(len(units(out)), 2)
        self.assertEqual(check_unit(units(out)[0], s, validate), ("ok", "ok"))
        self.assertEqual(len(repot(out, s, lambda a: dict(a, id=10))), 3)  # idempotent


if __name__ == "__main__":
    unittest.main()
