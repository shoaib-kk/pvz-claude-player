"""
The AI game loop. The game is never paused: Claude thinks in the background
while the game keeps running.

    python agent.py                     # Claude plays, using your Claude login
    python agent.py --restart           # restart the current level and play it from scratch
    python agent.py --brain simple      # rule-based test player, no Claude needed
    python agent.py --brain claude      # Claude via API key instead of your login

How it works:
  * Main loop (every 0.15 s, never waits for the AI):
      - collects sun and money (a scripted reflex, not an AI decision)
      - carries out the AI's current plan: each queued action happens as soon as
        there's enough sun and the seed has recharged; illegal ones are skipped
      - spots the end of the level (clicks the reward if won)
  * AI thread: whenever the plan runs out or something important happens
    (new zombie, plant lost, mower used), the board is sent to the brain.
    The player chooses whether to keep, append, cancel IDs, or replace its queue.
  * Everything goes to logs/, and the AI's reasoning to overlay.txt
    (add it to OBS as a Text (GDI+) source with "Read from file").

Stop with Ctrl+C, or slam the mouse into a screen corner.
"""

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pyautogui
import win32gui

import offsets as O
import plant_info
import vasebreaker
from brains import action_text, describe, make_brain, shot_behind_zombies, x_to_col
from journal import Journal, LevelRecorder, situation_of
from controller import Controller
from execution import ExecutionTracker
from emergency_stop import StopHotkey
from queueing import edit_queue, units, check_unit

ROOT = Path(__file__).parent
TICK = 0.15                # main loop period (sun pickup, plan execution)
MIN_GAP = 4.0              # never start a new AI request sooner than this after the last one
THREAT_GAP = 10.0          # a threat change waits this long since the last request, unless a mower fired
REJECTED_GAP = 8.0         # re-ask this soon when every action of the last plan was rejected
MAX_GAP = 30.0             # check lower-priority changes after this much time
FINAL_REWARDS = {7, 8, 9, 10, 11, 12, 13, 14, 15, 18}   # seed packet, note, trophy, money bag...
MAX_ACTIONS = 5            # length of the AI's build queue
# Re-export for existing callers and offline audits.
from placement import validate, UPGRADES, AQUATIC, SUPPORTS, BOWLING_SEEDS, ACTION_TYPES


# ---------------------------------------------------------------------------
# When is a new AI decision worth asking for?
# ---------------------------------------------------------------------------

def decision_context(state):
    ready = Counter((s["name"], s["cost"] or 0) for s in state["seeds"]
                    if s["ready"] and not s["name"].startswith("unknown")
                    and (s["cost"] or 0) <= state["sun"])
    return threats(state), ready, tuple(state.get("wave", ())), has_vases(state)


def has_vases(state):
    return state.get("special") == "vases" and any(i["type"] == "vase" for i in state.get("items", []))


def threats(state):
    """A zombie arriving in a new row/zone, a plant being eaten, a mower being used."""
    zs = [z for z in state["zombies"] if z["x"] < 760]
    return (
        frozenset((z["row"], z["type"], x_to_col(z["x"]) <= 4, x_to_col(z["x"]) <= 2) for z in zs),
        frozenset((p["row"], p["col"], p["type"]) for p in state["plants"]),
        tuple(state.get("mowers", [])),
    )


def important_change(old, new):
    if old is None:
        return True
    old_z, old_p, old_m = old
    new_z, new_p, new_m = new
    return bool(new_z - old_z) or bool(old_p - new_p) or old_m != new_m


def decision_reason(current, previous, *, conveyor, queued, completed, since, fruitless, retry=False,
                    rejected=False, vase_observation=None, previous_vase_observation=None):
    current_threats, ready, _, vases = current
    if since < MIN_GAP:
        return None
    if previous is None:
        return "first_board"
    if vase_observation is not None and previous_vase_observation is not None:
        positions, packets, expiring = vase_observation
        old_positions, old_packets, old_expiring = previous_vase_observation
        if positions - old_positions:
            return "vase_arrangement_changed"
        if positions != old_positions or packets != old_packets:
            return "vase_revealed"
        if expiring - old_expiring:
            return "packet_expiring"
    old_threats, old_ready, _, _ = previous
    can_act = bool(ready) or vases
    # Keep the ten-second throttle as a call-rate safety net. A new answer may keep the queue.
    mower_fired = old_threats is not None and old_threats[2] != current_threats[2]
    if can_act and important_change(old_threats, current_threats) and (since >= THREAT_GAP or mower_fired):
        return "threat_changed"
    new_cards = ready - old_ready
    if not queued and conveyor and new_cards:
        return "card_available"
    if fruitless >= 3 and since < MAX_GAP:
        return None
    # Every action of the last plan was rejected (cell taken, out of range...): let the player
    # see why and try again soon, instead of idling until the board changes.
    if not queued and rejected and since >= REJECTED_GAP:
        return "plan_rejected"
    can_buy = bool(ready) or vases
    if not queued and completed and can_buy:
        return "plan_completed"
    if not queued and new_cards:
        return "card_available"
    if since >= MAX_GAP and retry:
        return "retry"
    if since >= MAX_GAP and can_buy and current != previous:
        return "board_changed"
    # Vasebreaker waits for the player: with nothing queued and no zombies, the board never
    # changes on its own, so ask again or the level stalls forever.
    if not queued and vases and not current_threats[0] and since >= MAX_GAP:
        return "vase_idle"
    idle_gap = MAX_GAP * min(4, 2 ** max(0, fruitless - 2))
    if not queued and since >= idle_gap and any(cost == 0 for _, cost in ready):
        return "idle_check"
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self, brain, max_decisions=None, auto_sun=True, restart=False, levels=1, retries=0,
                 until_level=50, journal=True, journal_dir=None, max_attempts=None):
        self.ctl = Controller(move_duration=0.08)
        if not self.ctl.reader:
            sys.exit("Can't read game memory. Is Plants vs. Zombies running? (run as admin if needed)")
        self.reader = self.ctl.reader
        self.brain = brain
        self.max_decisions = max_decisions
        self.auto_sun = auto_sun
        self.restart = restart
        self.levels = levels
        self.retries = retries
        self.max_attempts = max_attempts
        self.until_level = until_level
        self.journal = Journal(journal_dir) if journal else None
        self.recorder = None
        self.loadout = []
        self.reset_plan()
        self.board_at_start = None
        self.decisions = 0
        (ROOT / "logs").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = ROOT / "logs" / f"run_{stamp}_{brain.name}.jsonl"
        self.overlay = ROOT / "overlay.txt"

    def reset_plan(self):
        self.recent = []
        self.queue = []
        self.had_plan = False
        self.planted_since_ask = 0
        self.rejected_since_ask = 0
        self.countered_boss_projectile = None
        self.plant_seen = {}           # (row, col, type) -> when it was first seen
        self.sun_gains = []            # (time, sun gained) over the last minute
        self.last_sun = None
        self.last_mowers = None
        self.level_finished = False
        self.execution = None
        self.vase_observer = vasebreaker.Observer()

    # --- small helpers -------------------------------------------------------
    def log(self, **entry):
        entry["t"] = datetime.now().isoformat(timespec="milliseconds")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def show(self, text):
        print(text)
        try:
            self.overlay.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def ensure_focus(self):
        """The game pauses itself when it loses focus; bring it back if so."""
        if win32gui.GetForegroundWindow() != self.ctl.hwnd:
            self.ctl.wake()
        board = self.reader.board()
        if board and self.reader.paused(board):
            self.ctl.wake()
        if board and self.reader.paused(board):
            self.ctl.resume()

    def snapshot(self):
        s = self.reader.snapshot()
        if s.get("errors"):
            self.log(kind="read_error", errors=s["errors"])
        if s.get("in_level") and "plants" in s:
            self.annotate(s)
            s["observed_at"] = datetime.now().isoformat(timespec="milliseconds")
            recorder = getattr(self, "recorder", None)
            if recorder:
                s["plan_progress"] = recorder.progress.report(s)
        return s

    def event(self, text):
        """Something the player would notice on screen, reported with its next board."""
        self.recent = (self.recent + [f"EVENT: {text}"])[-20:]
        self.log(kind="event", text=text)

    def annotate(self, s):
        """Facts a human sees but memory doesn't hold directly: how long each plant has
        been in the ground (a Potato Mine arms after ~15 s) and sun collected per minute."""
        now = time.monotonic()
        observer = getattr(self, "vase_observer", None)
        if observer and not getattr(self, "level_finished", False):
            for message in observer.observe(s):
                self.event(message)
                if getattr(self, "recorder", None):
                    self.recorder.events.append(message)
        seen = getattr(self, "plant_seen", None)
        if seen is None:
            return
        present = set()
        for p in s["plants"]:
            key = (p["row"], p["col"], p["type"])
            present.add(key)
            p["age"] = round(now - seen.setdefault(key, now), 1)
        for key in list(seen):
            if key not in present:
                row, col, kind = key
                age = now - seen.pop(key)
                if kind == "potato_mine":   # what a player sees: did the mine go off or get eaten?
                    if age < plant_info.POTATO_MINE_ARM_SECONDS:
                        self.event(f"your potato_mine at row {row} col {col} was eaten {age:.0f}s after "
                                   "planting, before it armed")
                    else:
                        self.event(f"your potato_mine at row {row} col {col} exploded")
        mowers = s.get("mowers")
        if getattr(self, "level_finished", False):
            mowers = None                      # end-of-level mower cash-in, not a defence
        if mowers and self.last_mowers and len(mowers) == len(self.last_mowers):
            for row, (old, new) in enumerate(zip(self.last_mowers, mowers)):
                if old and not new:
                    self.event(f"the lawn mower in row {row} fired; row {row} has no mower now")
        if mowers:
            self.last_mowers = list(mowers)
        sun = s.get("sun")
        if sun is not None:
            if self.last_sun is not None and sun > self.last_sun:
                self.sun_gains.append((now, sun - self.last_sun))
            self.last_sun = sun
            self.sun_gains = [(t, g) for t, g in self.sun_gains if now - t <= 60]
            s["sun_per_min"] = sum(g for _, g in self.sun_gains)

    # --- before the level ----------------------------------------------------
    def restart_level(self):
        """Menu -> Restart Level -> Restart."""
        self.show("Restarting the level...")
        if self.reader.scene() == "zombies_won":
            self.ctl.focus()
            self.ctl.click(395, 366)
            time.sleep(2)
            return
        if self.reader.scene() != "playing":
            return
        self.ensure_focus()
        self.ctl.click(740, 12)    # Menu
        time.sleep(1.0)
        self.ctl.click(397, 356)   # Restart Level
        time.sleep(1.0)
        self.ctl.click(303, 394)   # Restart (confirm)
        time.sleep(2.5)

    def get_to_playing(self, timeout=120, previous_level=None, retry=False):
        """Click through Crazy Dave, let the AI pick plants, wait for 'Ready, Set, Plant!'."""
        import seed_select
        deadline = time.monotonic() + timeout
        picked = False
        last_scene = None
        scene_since = time.monotonic()
        menu_clicked = False
        award_clicked = False
        zen_store = False
        while time.monotonic() < deadline:
            scene = self.reader.scene()
            if scene != last_scene:
                last_scene, scene_since = scene, time.monotonic()
                self.log(kind="transition", scene=scene, after_level=previous_level)
            elapsed = time.monotonic() - scene_since
            board = self.reader.board()
            if board and scene in ("intro", "playing") and self.reader.paused(board):
                self.ensure_focus()
            if board and self.reader.mode() == 43:   # mandatory first Zen Garden visit
                self.ctl.focus()
                tutorial = self.reader.tutorial(board)
                if tutorial == 25:
                    if not zen_store:
                        self.ctl.click(720, 53)     # Zen Garden Store
                        zen_store = True
                    else:
                        pyautogui.press("enter")    # store dialogue grants free fertilizer
                        self.ctl.click(400, 525)    # Back to Game
                elif self.reader.dave_talking() and tutorial not in (22, 23, 24, 26, 27):
                    pyautogui.press("enter")
                elif tutorial in (22, 23, 24, 26):
                    tool = (105, 38) if tutorial == 26 else (35, 38)
                    for point in self.reader.plant_points(board):
                        self.ctl.click(*tool)
                        self.ctl.click(*point)
                    pyautogui.click(button="right")
                elif tutorial == 27:
                    self.ctl.click(740, 12)         # Continue Adventure
                else:
                    pyautogui.press("enter")
                time.sleep(1)
                continue
            if scene == "playing":
                self.ensure_focus()
                return True
            if scene in ("challenge", "credits"):
                return False
            if scene == "loading":
                self.ctl.focus()
                self.ctl.click(400, 558)            # title screen's "Click to Start"
                time.sleep(1.5)
                continue
            if scene == "award":
                self.ctl.focus()
                if award_clicked and previous_level == 14 and elapsed > 2:
                    self.ctl.click(720, 580)        # Almanac Close
                elif award_clicked and previous_level in (24, 34, 41) and elapsed > 2:
                    pyautogui.press("enter")        # Dave's store intro advances on Enter
                    # Dave keeps an idle speech bubble in the store, so "talking" can stay set
                    # (seen after 4-4); the store screen itself means the intro is over.
                    if not self.reader.dave_talking() or self._store_visible():
                        self.ctl.click(*seed_select.STORE_NEXT_LEVEL)
                elif self._store_visible():
                    pyautogui.press("enter")        # finish any shop dialogue, then leave
                    self.ctl.click(*seed_select.STORE_NEXT_LEVEL)
                    self.log(kind="store_next_level", after_level=previous_level)
                else:
                    self.ctl.click(402, 520)
                award_clicked = True
                time.sleep(1.5)
                continue
            if scene == "zombies_won":
                if not retry:
                    return False
                self.ctl.focus()
                self.ctl.click(395, 366)           # Try Again on the Game Over screen
                time.sleep(2)
                continue
            if scene == "menu":
                self.ctl.focus()
                if not menu_clicked:
                    self.ctl.click(565, 130)       # Start/Continue Adventure
                    menu_clicked = True
                else:
                    self.ctl.click(285, 315)       # left button of the saved-game Continue dialog
                time.sleep(2)
                continue
            if scene == "intro":
                self.ctl.focus()
                if board and self.reader.tutorial(board) in (15, 16, 17):
                    state = self.reader.snapshot()
                    if state.get("plants"):
                        plant = state["plants"][0]
                        self.ctl.shovel(plant["row"], plant["col"], state["terrain"])
                        time.sleep(0.5)
                        continue
                if self.reader.dave_talking():
                    try:
                        offer = seed_select.slot_offer(seed_select.screenshot(self.ctl))
                    except Exception:  # noqa: BLE001 - no screenshot: just advance the dialogue
                        offer = False
                    if offer:
                        self.ctl.click(*seed_select.SLOT_OFFER_YES)   # Dave's seed-slot upgrade (game coins)
                        self.log(kind="seed_slot_upgrade", level=previous_level)
                        time.sleep(1.5)
                        continue
                    self.ctl.click(430, 120)
                    time.sleep(1.2)
                    continue
                if seed_select.in_chooser(self.ctl):
                    if not picked:
                        self.choose_plants()
                        picked = True
                    else:
                        self.ctl.click(*seed_select.LETS_ROCK)
                    time.sleep(1.5)
                    continue
                if elapsed > 10 and not picked:
                    self.ctl.click(400, 300)       # allow a skippable cinematic to advance
                    time.sleep(2)
                    continue
            time.sleep(0.5)
        return False

    def _store_visible(self):
        import seed_select
        try:
            return seed_select.store_screen(seed_select.screenshot(self.ctl))
        except Exception:  # noqa: BLE001 - no screenshot (tests, locked screen)
            return False

    def choose_plants(self):
        import seed_select
        self.show("Choosing plants...")
        t0 = time.time()
        try:
            info = self.reader.level_info(self.reader.board())
            self.brain.level = info["level"]
            journal = getattr(self, "journal", None)
            if journal:
                label = f"{(info['level'] - 1) // 10 + 1}-{(info['level'] - 1) % 10 + 1}" if info.get("level") else None
                self.brain.notes = journal.prompt_block(situation_of(info), label)
        except Exception:  # noqa: BLE001 - only used to stage knowledge
            pass
        names, why, warned = seed_select.choose(self.ctl, self.brain, log=print)
        self.loadout = list(names)
        self.pick_options = getattr(self.brain, "last_options", None)
        self.loadout_warning = warned
        plan = getattr(self.brain, "plan", None)
        self.show(f"Loadout: {', '.join(names)}. {why}" + (f"\n    Plan: {plan}" if plan else ""))
        self.log(kind="seed_pick", seeds=names, reasoning=why, warned=warned, plan=plan,
                 objectives=getattr(self.brain, "objectives", []),
                 options=getattr(self.brain, "last_options", None),
                 think_seconds=round(time.time() - t0, 1), **self.usage_fields())

    # --- during the level ----------------------------------------------------
    def collect(self):
        """Pick up sun and money. Runs every tick, whatever the AI is doing."""
        for coin in self.reader.coins(self.reader.board()):
            if (coin["type"] in O.SUN_TYPES or coin["type"] in O.MONEY_TYPES) \
                    and 0 <= coin["x"] < 800 and 0 <= coin["y"] < 600:
                self.ctl.click(coin["x"], coin["y"])

    def special_controls(self, state):
        """Handle reactions that need input faster than a Claude decision."""
        if state.get("tutorial") in (15, 16, 17) and state["plants"]:
            plant = state["plants"][0]
            self.ctl.shovel(plant["row"], plant["col"], state["terrain"])
            return True
        if state.get("special") == "whack":
            for zombie in state["zombies"]:
                x = zombie["x"] + 50
                if 0 <= x < 800 and zombie["row"] < len(state["grid"]):
                    _, y = self.ctl.cell_center(zombie["row"], 0, state["terrain"])
                    self.ctl.click(x, y)
                    break
            return True
        if state.get("special") == "boss":
            boss = next((z for z in state["zombies"] if z["type"] == "dr_zomboss"), {})
            ball = boss.get("projectile")
            if ball and ball["id"] != self.countered_boss_projectile:
                seed_name = "ice_shroom" if ball["type"] == "fire" else "jalapeno"
                rows = range(state["rows"]) if seed_name == "ice_shroom" else (ball["row"],)
                for row in rows:
                    for col in range(O.COLS - 1):
                        action = {"type": "plant", "seed": seed_name, "row": row, "col": col}
                        status, _, seed = validate(action, state)
                        if status == "ok" and self.perform(action, seed, state):
                            self.countered_boss_projectile = ball["id"]
                            self.log(kind="boss_counter", projectile=ball, action=action)
                            return True
        return False

    def perform(self, action, seed, state):
        """Click one action and confirm the change at its target or in its seed source."""
        row, col = action["row"], action["col"]
        terrain = state.get("terrain", "day")
        kind = action["type"]
        for _ in range(2):
            if self.reader.scene() != "playing" or self.reader.board() != self.board_at_start:
                return False
            if kind == "plant":
                self.ctl.plant(seed["slot"], row, col, terrain, seed.get("pickup"))
            elif kind == "break_vase":
                self.ctl.click(*self.ctl.cell_center(row, col, terrain))
            else:
                self.ctl.shovel(row, col, terrain)
            time.sleep(0.2)
            after = self.snapshot()
            if not self.readable(after):
                return False
            before_types = {p["type"] for p in state["plants"] if (p["row"], p["col"]) == (row, col)}
            after_types = {p["type"] for p in after["plants"] if (p["row"], p["col"]) == (row, col)}
            if kind == "break_vase" and validate(action, after)[0] == "reject":
                return True
            if kind == "shovel" and before_types - after_types:
                self.last_action_after = after
                return True
            if kind == "plant":
                source_before = sum(p["name"] == seed["name"] for p in state["seeds"])
                source_after = sum(p["name"] == seed["name"] for p in after["seeds"])
                recharging = not state.get("conveyor") and seed.get("pickup") is None and any(
                    p["slot"] == seed["slot"] and p["name"] == seed["name"] and not p["ready"]
                    for p in after["seeds"]
                )
                if seed["name"] in after_types - before_types or source_after < source_before or recharging:
                    self.last_action_after = after
                    return True
            status, _, seed = validate(action, after)
            if status != "ok":
                return False
            state = after
            self.ensure_focus()
        return False

    @staticmethod
    def readable(state):
        required = {"grid", "plants", "zombies", "seeds", "sun", "cells", "items"}
        return state.get("in_level") and required <= state.keys()

    def work_queue(self):
        """Execute only the ordering, independence, and groups chosen by the player."""
        while self.queue:
            state = self.snapshot()
            if not self.readable(state):
                return
            selected = None
            barrier = None
            for unit in units(self.queue):
                if barrier is not None and not unit[0].get("independent", False):
                    if self.execution:
                        for a in unit:
                            self.execution.waiting(a, f"queue order after #{barrier}")
                    continue
                status, reason = check_unit(unit, state, validate)
                if status == "later":
                    if self.execution:
                        for a in unit:
                            self.execution.waiting(a, reason)
                    if barrier is None:
                        barrier = unit[0].get("id", "?")
                else:
                    selected = (unit, status, reason)
                    break
            if selected is None:
                if self.execution:
                    self.execution.sample(True, state["sun"])
                return
            unit, status, reason = selected
            if self.execution:
                self.execution.sample(False, state["sun"])
            group_failed = status == "reject"
            for action in unit:
                self.queue.remove(action)
                if group_failed:
                    self.record_action(action, "reject", reason, None, state)
                    continue
                live = self.snapshot()
                if not self.readable(live):
                    group_failed, reason = True, "board became unreadable during group"
                    self.record_action(action, "reject", reason, None, state)
                    continue
                current, reason, seed = validate(action, live)
                if current != "ok":
                    group_failed = True
                    self.record_action(action, "reject", f"group interrupted: {reason}", seed, live)
                    continue
                if not self.record_action(action, current, reason, seed, live):
                    group_failed, reason = True, "earlier group step failed"
        if self.execution:
            self.execution.sample(False, 0)

    def record_action(self, action, status, reason, seed, state):
        """Perform one validated move, then record its real outcome and feedback."""
        desc = json.dumps({k: v for k, v in action.items() if v is not None and not k.startswith("_")})
        ok = False
        if status == "reject":
            self.rejected_since_ask = getattr(self, "rejected_since_ask", 0) + 1
            result = f"SKIPPED {desc}: {reason}"
            if self.execution:
                self.execution.finish(action, "rejected", reason)
        else:
            self.last_action_after = None
            ok = self.perform(action, seed, state)
            recorder = getattr(self, "recorder", None)
            if ok and recorder:
                recorder.record_action(action, seed, state, self.last_action_after)
            self.planted_since_ask += ok
            result = f"{'OK' if ok else 'FAILED (click did not register)'} {desc}"
            if self.execution:
                self.execution.finish(action, "completed" if ok else "failed", "" if ok else "click did not register")
                self.execution.sample(False, state["sun"])
            if ok and action["type"] == "plant" and shot_behind_zombies(
                    state, action["row"], action["col"], seed["name"]):
                r, c = action["row"], action["col"]
                self.event(f"your {seed['name']} at row {r} col {c} was planted behind every zombie "
                           f"in row {r}; its shots go toward the street, so it can't hit them")
        print("    " + result)
        feedback = f"{result.split(' ', 1)[0]} {action_text(action)}"
        if status == "reject":
            feedback += f": {reason}"
        elif not ok:
            feedback += ": click did not register"
        self.recent = (self.recent + [feedback])[-20:]
        self.log(kind="action", action=action, result=result)
        return ok

    def click_reward(self, state):
        for award in state.get("awards", []):
            if 0 <= award["x"] < 800 and 0 <= award["y"] < 600:
                self.ctl.click(award["x"], award["y"])
                self.log(kind="reward_clicked", type=award["type"], wave=state.get("wave"))
                if award["type"] in FINAL_REWARDS:
                    # The game then cashes in every unused mower (they all drive off).
                    # That isn't a mower saving a row, so stop recording from here on.
                    self.level_finished = True
                    if self.execution:
                        self.execution.sample(False, 0)
                return True
        return False

    def usage_fields(self):
        """The player's token usage for the call that just finished (for usage_report.py)."""
        usage = getattr(self.brain, "last_usage", None)
        usage = usage.to_dict() if hasattr(usage, "to_dict") else usage
        return {"usage": usage, "model": getattr(self.brain, "model", None)}

    def write_plan(self, label):
        """No plant chooser this level (conveyor, early levels...): ask for the plan now."""
        if not hasattr(self.brain, "write_plan"):
            return
        state = self.snapshot()
        if not self.readable(state):
            return
        t0 = time.time()
        try:
            plan = self.brain.write_plan(state)
        except Exception as e:  # noqa: BLE001 - play without a plan rather than stop
            self.log(kind="plan_error", level=label, error=str(e))
            return
        self.show(f"Plan for {label}: {plan}")
        self.log(kind="level_plan", level=label, plan=plan, think_seconds=round(time.time() - t0, 1),
                 objectives=getattr(self.brain, "objectives", []),
                 **self.usage_fields())

    def reflect(self, label, outcome, situation=None):
        """Let the player rewrite its journal after a finished level."""
        journal, recorder = getattr(self, "journal", None), getattr(self, "recorder", None)
        if not journal or not recorder:
            return
        board_text = describe(recorder.last, []) if recorder.last else None
        report = recorder.report(board_text, outcome)
        if self.execution:
            report += "\n\n" + self.execution.report()
        report += "\n[b0] The final board above is the last observed board, not necessarily the exact loss instant."
        t0 = time.time()
        try:
            summary = journal.reflect(self.brain, label, outcome, report, situation,
                                      getattr(self.brain, "plan", None),
                                      attempt=self.execution.attempt if self.execution else None,
                                      evidence=self.reflection_evidence(), facts=self.attempt_facts())
        except Exception as e:  # noqa: BLE001 - the journal must never stop a run
            self.log(kind="journal_error", level=label, error=str(e))
            return
        if summary is None:
            return
        lessons = "".join("\n    - " + x for x in journal.lessons)
        self.show(f"Journal after {label} ({outcome}): {summary}{lessons}")
        self.log(kind="journal", level=label, outcome=outcome, summary=summary, lessons=journal.lessons,
                 report=report, plan_assessment=journal.data["history"][-1].get("plan_assessment"),
                 think_seconds=round(time.time() - t0, 1), **self.usage_fields())

    def attempt_facts(self):
        """Comparable numbers for this attempt, for the journal's earlier-attempts table."""
        facts = self.recorder.facts() if getattr(self, "recorder", None) else None
        if facts and self.execution:
            m = self.execution.metrics()
            facts["plants_placed"] = sum(m.get("planted", {}).values()) or facts["plants_placed"]
            facts["planted"] = dict(m.get("planted", {}))
            facts["stalled_unspent_sun_seconds"] = m.get("queue_stalled_unspent_sun_seconds")
        return facts

    def reflection_evidence(self):
        """Only recorded facts, never operator conclusions about the player's choices."""
        evidence = {}
        if self.execution:
            evidence.update({e["event_id"]: e for e in self.execution.events})
            evidence["s0"] = self.execution.metrics()
        if self.recorder:
            evidence["p0"] = self.recorder.progress.status(self.recorder.last or {})
            evidence["a0"] = self.recorder.purchases.metrics()
            evidence.update({f"t{i}": event for i, event in enumerate(self.recorder.events, 1)})
            evidence["b0"] = self.recorder.last
        return evidence

    def capture_result(self, level, outcome):
        stamp = datetime.now().strftime("%H-%M-%S-%f")
        path = self.log_path.with_name(f"{self.log_path.stem}_level_{level}_{outcome}_{stamp}.png")
        try:
            origin = self.ctl.to_screen(0, 0)
            pyautogui.screenshot(region=(*origin, 800, 600)).save(path)
            self.log(kind="result_screenshot", level=level, outcome=outcome, file=path.name)
        except OSError as error:
            self.log(kind="screenshot_error", level=level, error=str(error))

    def ask_brain(self, state, recent, queue, trigger):
        """Runs in the background thread."""
        t0 = time.time()
        try:
            decision = self.brain.decide(state, recent, queue)
        except Exception as e:  # noqa: BLE001 - keep playing if one call fails
            decision = {"reasoning": f"(brain error: {type(e).__name__}: {e})", "_error": True}
        decision["_think"] = round(time.time() - t0, 2)
        decision["_state"] = state
        decision["_trigger"] = trigger
        decision["_queue_ids"] = [a["id"] for a in queue if "id" in a]
        decision["_usage"] = self.usage_fields()
        return decision

    def apply_decision(self, decision):
        self.decisions += 1
        if not decision.get("_error"):
            if self.execution is None:
                self.execution = ExecutionTracker("offline", self.log)
            self.queue = [a if a.get("id") in self.execution.actions else self.execution.issue(a, 0)
                          for a in self.queue]
            try:
                live = self.snapshot() if decision.get("_queue_ids") else decision["_state"]
                self.queue = edit_queue(self.queue, decision, self.execution, self.decisions, live)
                if decision.get("edit") != "keep":
                    self.had_plan = bool(self.queue)
            except (ValueError, TypeError, KeyError) as error:
                decision["_error"] = True
                self.event(f"queue edit rejected; your queue was kept: {error}")
                self.execution.event("queue_edit_rejected", decision=self.decisions, reason=str(error))
        plan = ", ".join(f"{a.get('seed', a['type'])}@{a.get('row')},{a.get('col')}"
                         for a in self.queue) or "nothing for now"
        self.show(f"[{self.decisions}] ({decision['_think']}s) {decision.get('reasoning', '')}\n"
                  f"    plan: {plan}")
        self.log(kind="decision", n=self.decisions, think_seconds=decision["_think"],
                 state=decision["_state"], prompt=decision.get("_prompt"),
                 trigger=decision.get("_trigger"),
                 decision={k: v for k, v in decision.items() if not k.startswith("_")},
                 **decision["_usage"])

    def play(self):
        outcome = "stopped"
        previous_context, last_ask_t = None, 0.0
        previous_vase_observation = None
        last_reward_click = 0.0
        awaiting_result = False
        unreadable_since = None
        brain_errors = 0
        pending = None
        interrupted = False
        fruitless = 0            # AI plans in a row where nothing could be planted
        self.board_at_start = self.reader.board()
        level = self.reader.level_info(self.board_at_start)["level"]
        pool = ThreadPoolExecutor(max_workers=1)
        last_observe = 0.0
        try:
            while True:
                # Only ever play the level we started: stop if the game moved on
                # (next level's intro, menu, a restarted board...).
                scene = self.reader.scene()
                board = self.reader.board()
                if scene != "playing" or board != self.board_at_start:
                    time.sleep(0.5)
                    scene, board = self.reader.scene(), self.reader.board()
                    if scene != "playing" or board != self.board_at_start:
                        next_level = self.reader.level_info(board)["level"] if board else None
                        if scene == "zombies_won":
                            outcome = "lost"
                        elif scene == "award" or (level == 50 and scene == "credits"):
                            outcome = "won"
                        elif last_reward_click and level and next_level == level + 1:
                            outcome = "won"
                        else:
                            outcome = "left"
                        self.log(kind="level_end", level=level, scene=scene, next_level=next_level, outcome=outcome)
                        return outcome
                self.ensure_focus()
                state = self.snapshot()
                if not state.get("in_level"):
                    time.sleep(TICK)
                    continue

                if awaiting_result and time.monotonic() - last_reward_click < 15:
                    time.sleep(TICK)
                    continue
                awaiting_result = False
                if time.monotonic() - last_reward_click >= 3 and self.click_reward(state):
                    last_reward_click = time.monotonic()
                    awaiting_result = not state.get("zombies") and state["awards"][0]["type"] in FINAL_REWARDS
                    continue

                if not self.readable(state):
                    if unreadable_since is None:
                        unreadable_since = time.monotonic()
                    if time.monotonic() - unreadable_since >= 15:
                        self.log(kind="level_end", level=level, outcome="read_error", errors=state.get("errors"))
                        outcome = "read_error"
                        return outcome
                    time.sleep(TICK)
                    continue
                unreadable_since = None
                recorder = getattr(self, "recorder", None)
                if recorder and not getattr(self, "level_finished", False) \
                        and time.monotonic() - last_observe >= 1:
                    recorder.observe(state)
                    last_observe = time.monotonic()

                if self.reader.dave_talking():
                    pyautogui.press("enter")        # Vasebreaker and whack tutorial dialogue
                    time.sleep(0.5)
                    continue

                if self.auto_sun:
                    self.collect()

                if self.special_controls(state):
                    time.sleep(TICK)
                    continue

                if pending is not None and pending.done():
                    decision = pending.result()
                    self.apply_decision(decision)
                    brain_errors = brain_errors + 1 if decision.get("_error") else 0
                    pending = None
                    if brain_errors >= 3:
                        outcome = "brain_error"
                        return outcome
                    if self.max_decisions and self.decisions >= self.max_decisions:
                        outcome = "max_decisions"
                        return outcome

                self.work_queue()

                if pending is None:
                    state = self.snapshot()
                    if not self.readable(state):
                        time.sleep(TICK)
                        continue
                    now = time.monotonic()
                    context = decision_context(state)
                    trigger = decision_reason(
                        context, previous_context,
                        conveyor=state.get("conveyor") or state.get("special") == "vases",
                        queued=bool(self.queue), completed=self.had_plan and self.planted_since_ask > 0,
                        since=now - last_ask_t, fruitless=fruitless, retry=brain_errors > 0,
                        rejected=self.had_plan and self.planted_since_ask == 0 and self.rejected_since_ask > 0,
                        vase_observation=vasebreaker.context(state),
                        previous_vase_observation=previous_vase_observation,
                    )
                    has_usable_deck = any(not s["name"].startswith("unknown") for s in state["seeds"])
                    if trigger and (has_usable_deck or context[3]):
                        if previous_context is not None:
                            fruitless = fruitless + 1 if self.planted_since_ask == 0 else 0
                        self.planted_since_ask = 0
                        self.rejected_since_ask = 0
                        if self.execution:
                            state["execution"] = self.execution.compact()
                        pending = pool.submit(self.ask_brain, state, list(self.recent), list(self.queue), trigger)
                        previous_context, last_ask_t = context, now
                        previous_vase_observation = vasebreaker.context(state)

                time.sleep(TICK)
        except KeyboardInterrupt:
            interrupted = True
            cancel = getattr(self.brain, "cancel", None) if hasattr(self, "brain") else None
            if cancel:
                cancel()
            raise
        finally:
            # Freeze waits before waiting for an in-flight reply after the level ends.
            if self.execution:
                self.execution.end(self.queue, outcome)
            # A completed level can have an in-flight decision. Keep it from
            # racing the next level's chooser for the same player's usage.
            pool.shutdown(wait=not interrupted, cancel_futures=True)
            if pending is not None and pending.done() and not pending.cancelled():
                decision = pending.result()
                self.log(kind="unused_decision", trigger=decision["_trigger"],
                         think_seconds=decision["_think"], **decision["_usage"])

    def play_levels(self):
        wins = 0
        attempts = 0
        last_win = None
        retry = getattr(self, "restart", False)   # --restart may start on the Game Over screen
        retries_left = self.retries
        while wins < self.levels:
            if getattr(self, "max_attempts", None) is not None and attempts >= self.max_attempts:
                return "max_attempts", wins
            self.recorder = None  # previous attempt's objectives must not enter the next plan
            journal = getattr(self, "journal", None)
            if hasattr(self, "brain"):
                self.brain.plan = None       # written fresh for every attempt
                self.brain.objectives = []
                set_loadout = getattr(self.brain, "set_loadout", None)
                if set_loadout:
                    set_loadout([], None)
                if journal:
                    self.brain.notes = journal.prompt_block()
            if not self.get_to_playing(previous_level=last_win, retry=retry or self.retries > 0):
                self.show(f"Navigation stopped on the {self.reader.scene()} screen.")
                return "transition_stalled", wins
            info = self.reader.level_info(self.reader.board())
            level = info["level"]
            if level and level > self.until_level:
                self.show(f"Already beyond the requested Adventure level {self.until_level}.")
                return "target_reached", wins
            if self.levels > 1 and (level is None or (last_win is not None and level != last_win + 1)):
                self.show(f"Expected the next Adventure board but reached level {level}.")
                return "unexpected_level", wins
            self.reset_plan()
            label = f"{(level - 1) // 10 + 1}-{(level - 1) % 10 + 1}" if level else "current level"
            situation = situation_of(info)
            self.show(f"Level {label} started ({info['special'] or info['terrain']}).")
            self.log(kind="level_start", **info)
            if hasattr(self, "brain"):
                self.brain.level = level
                if set_loadout:
                    loadout = [] if info.get("conveyor") else list(getattr(self, "loadout", []))
                    set_loadout(loadout, level)
                if journal:
                    self.brain.notes = journal.prompt_block(situation, label)
                if self.brain.plan is None and info.get("special") != "whack":
                    self.write_plan(label)
                reset_brain = getattr(self.brain, "reset", None)
                if reset_brain and info.get("special") != "whack":
                    reset_brain()  # fresh conversation per level, with this level's journal and plan
            self.recorder = LevelRecorder(label, getattr(self, "loadout", []),
                                          getattr(self, "pick_options", None),
                                          getattr(getattr(self, "brain", None), "objectives", []))
            self.attempt_number = getattr(self, "attempt_number", 0) + 1
            self.execution = ExecutionTracker(
                f"{getattr(self, 'log_path', Path('test')).stem}:attempt{self.attempt_number}", self.log)
            self.pick_options = None         # only valid for the attempt whose chooser offered them
            if getattr(self, "loadout_warning", False):
                self.recorder.events.append("before the level: the game warned that your loadout "
                                            "had no sun-producing plant; you started anyway")
                self.loadout_warning = False
            result = self.play()
            attempts += 1
            self.execution.end(self.queue, result)
            # Whack-a-Zombie is played by the script (mallet clicks), not by the player,
            # so there is nothing for the player to reflect on.
            if result in ("won", "lost") and info.get("special") != "whack":
                self.reflect(label, result, situation)
            if result in ("won", "lost"):
                self.capture_result(level, result)
            if result == "won":
                wins += 1
                last_win = level
                retries_left = self.retries
                retry = False
                self.show(f"Level {label} complete.")
                if level == self.until_level or level == 50 or wins == self.levels:
                    return "won", wins
            elif result == "lost" and retries_left > 0:
                retries_left -= 1
                retry = True
                self.show(f"Retrying level {label} after a loss.")
            else:
                return result, wins

    def run(self):
        self.show(f"AI ({self.brain.name}) is taking over. Press Ctrl+C anywhere to stop.")
        import hashlib
        attempt_limit = getattr(self, "max_attempts", None)
        code_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in ROOT.glob("*.py")}
        self.log(kind="start", brain=self.brain.name, version=self.reader.version,
                 model=getattr(self.brain, "model", None), effort=getattr(self.brain, "effort", None),
                 max_attempts=attempt_limit, retries=getattr(self, "retries", 0),
                 plan_effort=getattr(self.brain, "plan_effort", None), code_sha256=code_hashes,
                 journal_sha256=(hashlib.sha256(self.journal.path.read_bytes()).hexdigest()
                                 if self.journal and self.journal.path.exists() else None),
                 architecture="player-queue-learning-v2")
        outcome, wins = "stopped", 0
        stop_hotkey = StopHotkey(cancel=getattr(self.brain, "cancel", None))
        self.ctl.stop_check = stop_hotkey.check
        stop_hotkey.start()
        try:
            self.ctl.wake()
            if self.restart:
                self.restart_level()
            outcome, wins = self.play_levels()
            messages = {"won": f"Completed {wins} level(s).",
                        "max_attempts": f"Completed {attempt_limit} attempts; won {wins} level(s).",
                        "lost": "The zombies ate the AI's brains. Level lost.",
                        "left": "The level was closed.",
                        "max_decisions": f"Stopped after {self.decisions} decisions (--max-decisions).",
                        "unexpected_level": "Stopped on an unexpected board.",
                        "transition_stalled": "Stopped while navigating to the next level.",
                        "read_error": "Stopped after repeated unreadable board state.",
                        "brain_error": "Stopped after three consecutive player errors."}
            messages["target_reached"] = "The requested Adventure endpoint has already been passed."
            self.show(messages.get(outcome, outcome))
        except KeyboardInterrupt:
            stop_hotkey.close()
            cancel = getattr(self.brain, "cancel", None)
            if cancel:
                cancel()
            outcome = "stopped"
            self.show("Stopped by you.")
            if self.reader.scene() == "playing" and self.reader.board():
                self.ctl.pause()
        except pyautogui.FailSafeException:
            self.show("Stopped: mouse hit a screen corner (fail-safe).")
        finally:
            stop_hotkey.close()
            close = getattr(self.brain, "close", None)
            if close:
                close()
            if self.execution:
                self.execution.end(self.queue, outcome)
            self.log(kind="stop", outcome=outcome, decisions=self.decisions, wins=wins)
            print(f"Log: {self.log_path}")


def main():
    ap = argparse.ArgumentParser(description="Let an AI play Plants vs. Zombies.")
    ap.add_argument("--brain", default="subscription", choices=["subscription", "claude", "simple"],
                    help="subscription = Claude via your Claude login (default); "
                         "claude = Claude API key; simple = rule-based test bot")
    ap.add_argument("--restart", action="store_true",
                    help="restart the current level from its menu first (play it from scratch)")
    ap.add_argument("--max-decisions", type=int, default=None)
    ap.add_argument("--no-auto-sun", action="store_true", help="don't collect sun automatically")
    levels = ap.add_mutually_exclusive_group()
    levels.add_argument("--levels", type=int, default=1, metavar="N",
                        help="play up to N consecutive Adventure levels (default: one)")
    levels.add_argument("--campaign", action="store_const", const=50, dest="levels",
                        help="advance through Adventure until level 5-10 or a stop condition")
    levels.add_argument("--until-level", type=int, metavar="N",
                        help="advance through Adventure and stop after absolute level N (1-50)")
    ap.add_argument("--retries", type=int, default=0, metavar="N",
                    help="retry a lost level up to N times")
    ap.add_argument("--max-attempts", type=int, metavar="N",
                    help="stop after N total attempts, counting wins and losses across levels")
    ap.add_argument("--no-journal", action="store_true",
                    help="don't read or write the player's lessons journal (journal/lessons.json)")
    ap.add_argument("--journal-dir", metavar="DIR",
                    help="keep the journal in DIR instead of journal/ (e.g. one per model)")
    args = ap.parse_args()
    if not 1 <= args.levels <= 50 or args.retries < 0 or (
        args.until_level is not None and not 1 <= args.until_level <= 50
    ) or (
        args.max_attempts is not None and args.max_attempts < 1
    ):
        ap.error("level limits must be 1 through 50, --retries nonnegative, and --max-attempts positive")
    try:
        brain = make_brain(args.brain)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Couldn't start the {args.brain} brain: {e}")
    Agent(brain, max_decisions=args.max_decisions, auto_sun=not args.no_auto_sun,
          restart=args.restart, levels=50 if args.until_level else args.levels, retries=args.retries,
          until_level=args.until_level or 50, journal=not args.no_journal,
          journal_dir=args.journal_dir, max_attempts=args.max_attempts).run()


if __name__ == "__main__":
    main()
