"""Stop-key and in-flight cancellation tests; no game input or Claude calls."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pvz.player.brains import ClaudeCodeBrain
from pvz.game.controller import Controller
from pvz.game.emergency_stop import StopHotkey
from tests.test_campaign import operator


class StopKeyTests(unittest.TestCase):
    def test_requires_both_keys_down_and_only_interrupts_once(self):
        held = set()
        cancel, interrupt = Mock(), Mock()
        stop = StopHotkey(cancel, lambda key: 0x8000 if key in held else 1, interrupt)
        stop.poll()
        held.add(0x11)
        stop.poll()
        interrupt.assert_not_called()
        held.add(ord("C"))
        stop.poll()
        stop.poll()
        cancel.assert_called_once()
        interrupt.assert_called_once()
        with self.assertRaises(KeyboardInterrupt):
            stop.check()

    def test_background_listener_and_shutdown(self):
        interrupted = threading.Event()
        stop = StopHotkey(key_state=lambda key: 0x8000, interrupt=interrupted.set)
        stop.start()
        self.assertTrue(interrupted.wait(timeout=1))
        stop.close()
        self.assertFalse(stop.thread.is_alive())

    def test_stop_during_mouse_movement_prevents_the_click(self):
        stop = StopHotkey(key_state=lambda key: 0, interrupt=Mock())
        ctl = Controller.__new__(Controller)
        ctl.stop_check = stop.check
        ctl.hover = Mock(side_effect=lambda *args: stop.requested.set())
        with patch("pvz.game.controller.pyautogui.click") as click:
            with self.assertRaises(KeyboardInterrupt):
                ctl.click(200, 200)
            click.assert_not_called()

    def test_run_stops_and_pauses_without_advancing(self):
        op = operator()
        op.brain = SimpleNamespace(name="test", cancel=Mock(), close=Mock())
        op.journal = None
        op.restart = False
        op.log_path = "offline"
        op.reader.version = "test"
        op.reader.scene.return_value = "playing"
        op.reader.board.return_value = 100
        op.play_levels = Mock(side_effect=KeyboardInterrupt)
        with patch("pvz.agent.StopHotkey") as hotkey:
            op.run()
            hotkey.return_value.close.assert_called()
        op.ctl.pause.assert_called_once()
        op.brain.cancel.assert_called_once()
        op.brain.close.assert_called_once()
        op.log.assert_called_with(kind="stop", outcome="stopped", decisions=0, wins=0)


def brain():
    player = ClaudeCodeBrain.__new__(ClaudeCodeBrain)
    player._cancelled = threading.Event()
    player._lock = threading.Lock()
    player._proc = None
    player._one_shot = None
    player.timeout = 10
    player._base_cmd = Mock(return_value=["unused-test-executable"])
    return player


class PlayerCancellationTests(unittest.TestCase):
    def test_cancel_kills_only_its_own_processes_without_taking_busy_lock(self):
        player = brain()
        player._proc, player._one_shot = Mock(), Mock()
        player._proc.poll.return_value = None
        player._one_shot.poll.return_value = None
        with player._lock:
            player.cancel()
        player._proc.kill.assert_called_once()
        player._one_shot.kill.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "canceled"):
            player._start()

    def test_one_shot_is_cancelable_and_cannot_return_a_late_plan(self):
        player = brain()
        proc = Mock()
        proc.poll.return_value = None
        def reply(**kwargs):
            self.assertIs(player._one_shot, proc)
            player.cancel()
            return '{"structured_output":{"plan":"late"}}', ""
        proc.communicate.side_effect = reply
        with patch("subprocess.Popen", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "canceled"):
                player.ask("system", "board", {})
        proc.kill.assert_called_once()
        self.assertIsNone(player._one_shot)

    def test_normal_one_shot_still_parses_the_player_response(self):
        player = brain()
        proc = Mock()
        proc.communicate.return_value = ('{"structured_output":{"plan":"my plan"}}', "")
        with patch("subprocess.Popen", return_value=proc):
            self.assertEqual(player.ask("system", "board", {}), {"plan": "my plan"})
        self.assertIsNone(player._one_shot)


if __name__ == "__main__":
    unittest.main()
