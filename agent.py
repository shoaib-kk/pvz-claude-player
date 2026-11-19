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
    Its new plan replaces the old one when the answer arrives.
  * Everything goes to logs/, and the AI's reasoning to overlay.txt
    (add it to OBS as a Text (GDI+) source with "Read from file").

Stop with Ctrl+C, or slam the mouse into a screen corner.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pyautogui
import win32gui

import offsets as O
import plant_info
from brains import describe, make_brain, x_to_col
from journal import Journal, LevelRecorder, situation_of
from controller import Controller

ROOT = Path(__file__).parent
TICK = 0.15                # main loop period (sun pickup, plan execution)
MIN_GAP = 4.0              # never start a new AI request sooner than this after the last one
MAX_GAP = 30.0             # re-plan at least this often while something is affordable
FINAL_REWARDS = {7, 8, 9, 10, 11, 12, 13, 14, 15, 18}   # seed packet, note, trophy, money bag...
MAX_ACTIONS = 5            # length of the AI's build queue
UPGRADES = {"gatling_pea": "repeater", "twin_sunflower": "sunflower", "gloom_shroom": "fume_shroom",
            "cattail": "lily_pad", "winter_melon": "melon_pult", "gold_magnet": "magnet_shroom",
            "spikerock": "spikeweed", "cob_cannon": "kernel_pult"}
AQUATIC = {"lily_pad", "sea_shroom", "tangle_kelp"}
SUPPORTS = {"lily_pad", "flower_pot"}
BOWLING_SEEDS = {"wall_nut", "explode_o_nut", "giant_wall_nut"}
ACTION_TYPES = {"plant", "shovel", "break_vase"}


# ---------------------------------------------------------------------------
# Validation: never let the AI click something illegal
# ---------------------------------------------------------------------------

def validate(action, state):
    """Check one action against the live board.
    Returns (status, reason, seed) where status is
      "ok"     - do it now
      "later"  - legal, but wait for sun / the seed to recharge
      "reject" - can never work as written"""
    kind = action.get("type")
    row, col = action.get("row"), action.get("col")
    if not isinstance(row, int) or not isinstance(col, int):
        return "reject", "row and col are required", None
    if not (0 <= row < len(state["grid"]) and 0 <= col < O.COLS):
        return "reject", f"cell ({row},{col}) is off the lawn", None
    occupant = state["grid"][row][col]
    plants = {p["type"]: p for p in state["plants"] if (p["row"], p["col"]) == (row, col)}
    cells = state.get("cells")
    cell = cells[row][col] if cells else O.CELL_GRASS
    items = {i["type"] for i in state.get("items", []) if (i["row"], i["col"]) == (row, col)}
    special = state.get("special")

    if kind == "break_vase":
        if special == "vases" and "vase" in items:
            return "ok", "ok", None
        return "reject", "no vase at that cell", None

    if kind == "shovel":
        if not plants and occupant is None:
            return "reject", f"nothing to shovel at ({row},{col})", None
        return "ok", "ok", None

    if kind == "plant":
        name = (action.get("seed") or "").strip().lower().replace(" ", "_").replace("-", "_")
        matches = [s for s in state["seeds"] if s["name"] == name]
        seed = next((s for s in matches if s["ready"]), matches[0] if matches else None)
        if seed is None:
            have = ", ".join(s["name"] for s in state["seeds"])
            return "reject", f"you don't have {name!r} (you have: {have})", None
        if special == "bowling":
            if col > 2 or name not in BOWLING_SEEDS:
                return "reject", "roll a nut from columns 0 through 2", None
        elif special == "boss" and col >= 8:
            return "reject", "the last roof column is reserved for Zomboss", None
        elif name == "coffee_bean":
            if not any(p.get("asleep") for p in plants.values()) or name in plants:
                return "reject", "Coffee Bean needs a sleeping mushroom", None
        elif name == "grave_buster":
            if "grave" not in items or occupant is not None:
                return "reject", "Grave Buster needs an uncovered grave", None
        elif cell in (0, O.CELL_DIRT) or items & {"grave", "crater", "vase", "ice"}:
            return "reject", "the cell is blocked", None
        elif name in AQUATIC:
            if cell != O.CELL_POOL or occupant is not None or plants.keys() & SUPPORTS:
                return "reject", f"{name} needs open water", None
        elif name == "flower_pot":
            if cell == O.CELL_POOL or plants or occupant is not None:
                return "reject", "Flower Pot needs an empty dry cell", None
        elif cell == O.CELL_POOL and "lily_pad" not in plants and name != "cattail" and not (
            name == "pumpkin" and occupant == "cattail"
        ):
            return "reject", "plant a Lily Pad here first", None
        elif state.get("terrain") in ("roof", "boss") and "flower_pot" not in plants:
            return "reject", "plant a Flower Pot here first", None
        elif name in {"spikeweed", "spikerock"} and plants.keys() & SUPPORTS:
            return "reject", f"{name} requires solid ground", None
        elif name == "pumpkin":
            if "pumpkin" in plants or occupant == "cob_cannon":
                return "reject", f"cannot cover ({row},{col}) with a pumpkin", None
        elif name in UPGRADES:
            if occupant != UPGRADES[name] and UPGRADES[name] not in plants:
                return "reject", f"{name} must go on top of a {UPGRADES[name]}", None
            if name == "cattail" and occupant is not None:
                return "reject", "Cattail needs a Lily Pad with no plant on top", None
            if name == "cob_cannon" and (col + 1 >= O.COLS or state["grid"][row][col + 1] != "kernel_pult"):
                return "reject", "cob_cannon needs two kernel_pults side by side (it goes on the left one)", None
        elif occupant is not None:
            return "reject", f"({row},{col}) already has a {occupant}", None
        if not seed["ready"]:
            return "later", f"{name} is recharging", seed
        if seed["cost"] is not None and seed["cost"] > state["sun"]:
            return "later", f"saving up for {name} ({seed['cost']} sun)", seed
        return "ok", "ok", seed
    return "reject", f"unknown action type {kind!r}", None


# ---------------------------------------------------------------------------
# When is a new AI decision worth asking for?
# ---------------------------------------------------------------------------

def affordable(state):
    return {s["name"] for s in state["seeds"] if s["ready"] and (s["cost"] or 0) <= state["sun"]}


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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self, brain, max_decisions=None, auto_sun=True, restart=False, levels=1, retries=0,
                 until_level=50, journal=True, journal_dir=None):
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
        self.countered_boss_projectile = None
        self.plant_seen = {}           # (row, col, type) -> when it was first seen
        self.sun_gains = []            # (time, sun gained) over the last minute
        self.last_sun = None
        self.last_mowers = None
        self.level_finished = False

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
        return s

    def event(self, text):
        """Something the player would notice on screen, reported with its next board."""
        self.recent = (self.recent + [f"EVENT: {text}"])[-20:]
        self.log(kind="event", text=text)

    def annotate(self, s):
        """Facts a human sees but memory doesn't hold directly: how long each plant has
        been in the ground (a Potato Mine arms after ~15 s) and sun collected per minute."""
        now = time.monotonic()
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
                    if not self.reader.dave_talking():
                        self.ctl.click(400, 525)    # store Back, also within Next Level
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

    def choose_plants(self):
        import seed_select
        self.show("Choosing plants...")
        t0 = time.time()
        try:
            info = self.reader.level_info(self.reader.board())
            self.brain.level = info["level"]
            journal = getattr(self, "journal", None)
            if journal:
                self.brain.notes = journal.prompt_block(situation_of(info))
        except Exception:  # noqa: BLE001 - only used to stage knowledge
            pass
        names, why, warned = seed_select.choose(self.ctl, self.brain, log=print)
        self.loadout = list(names)
        self.loadout_warning = warned
        plan = getattr(self.brain, "plan", None)
        self.show(f"Loadout: {', '.join(names)}. {why}" + (f"\n    Plan: {plan}" if plan else ""))
        self.log(kind="seed_pick", seeds=names, reasoning=why, warned=warned, plan=plan,
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
                return True
            if kind == "plant":
                source_before = sum(p["name"] == seed["name"] for p in state["seeds"])
                source_after = sum(p["name"] == seed["name"] for p in after["seeds"])
                recharging = not state.get("conveyor") and seed.get("pickup") is None and any(
                    p["slot"] == seed["slot"] and p["name"] == seed["name"] and not p["ready"]
                    for p in after["seeds"]
                )
                if seed["name"] in after_types - before_types or source_after < source_before or recharging:
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
        """Carry out queued actions in order, each as soon as it's possible."""
        while self.queue:
            state = self.snapshot()
            if not self.readable(state):
                return
            action = self.queue[0]
            status, reason, seed = validate(action, state)
            if status == "later":
                return
            self.queue.pop(0)
            desc = json.dumps({k: v for k, v in action.items() if v is not None})
            if status == "reject":
                result = f"SKIPPED {desc}: {reason}"
            else:
                ok = self.perform(action, seed, state)
                self.planted_since_ask += ok
                result = f"{'OK' if ok else 'FAILED (click did not register)'} {desc}"
            print("    " + result)
            self.recent = (self.recent + [result])[-20:]
            self.log(kind="action", action=action, result=result)

    def click_reward(self, state):
        for award in state.get("awards", []):
            if 0 <= award["x"] < 800 and 0 <= award["y"] < 600:
                self.ctl.click(award["x"], award["y"])
                self.log(kind="reward_clicked", type=award["type"], wave=state.get("wave"))
                if award["type"] in FINAL_REWARDS:
                    # The game then cashes in every unused mower (they all drive off).
                    # That isn't a mower saving a row, so stop recording from here on.
                    self.level_finished = True
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
                 **self.usage_fields())

    def reflect(self, label, outcome, situation=None):
        """Let the player rewrite its journal after a finished level."""
        journal, recorder = getattr(self, "journal", None), getattr(self, "recorder", None)
        if not journal or not recorder:
            return
        board_text = describe(recorder.last, []) if recorder.last else None
        report = recorder.report(board_text, outcome)
        t0 = time.time()
        try:
            summary = journal.reflect(self.brain, label, outcome, report, situation,
                                      getattr(self.brain, "plan", None))
        except Exception as e:  # noqa: BLE001 - the journal must never stop a run
            self.log(kind="journal_error", level=label, error=str(e))
            return
        if summary is None:
            return
        lessons = "".join("\n    - " + x for x in journal.lessons)
        self.show(f"Journal after {label} ({outcome}): {summary}{lessons}")
        self.log(kind="journal", level=label, outcome=outcome, summary=summary, lessons=journal.lessons,
                 report=report, think_seconds=round(time.time() - t0, 1), **self.usage_fields())

    def capture_result(self, level, outcome):
        stamp = datetime.now().strftime("%H-%M-%S-%f")
        path = self.log_path.with_name(f"{self.log_path.stem}_level_{level}_{outcome}_{stamp}.png")
        try:
            origin = self.ctl.to_screen(0, 0)
            pyautogui.screenshot(region=(*origin, 800, 600)).save(path)
            self.log(kind="result_screenshot", level=level, outcome=outcome, file=path.name)
        except OSError as error:
            self.log(kind="screenshot_error", level=level, error=str(error))

    def ask_brain(self, state, recent, queue):
        """Runs in the background thread."""
        t0 = time.time()
        try:
            decision = self.brain.decide(state, recent, queue)
        except Exception as e:  # noqa: BLE001 - keep playing if one call fails
            decision = {"reasoning": f"(brain error: {type(e).__name__}: {e})", "actions": queue,
                        "_error": True}
        decision["_think"] = round(time.time() - t0, 2)
        decision["_state"] = state
        return decision

    def apply_decision(self, decision):
        self.decisions += 1
        self.queue = [a for a in decision.get("actions", []) if a.get("type") in ACTION_TYPES]
        self.queue = self.queue[:MAX_ACTIONS]
        self.had_plan = bool(self.queue)
        plan = ", ".join(f"{a.get('seed', a['type'])}@{a.get('row')},{a.get('col')}"
                         for a in self.queue) or "nothing for now"
        self.show(f"[{self.decisions}] ({decision['_think']}s) {decision.get('reasoning', '')}\n"
                  f"    plan: {plan}")
        usage = getattr(self.brain, "last_usage", None)
        self.log(kind="decision", n=self.decisions, think_seconds=decision["_think"],
                 state=decision["_state"], prompt=decision.get("_prompt"),
                 decision={k: v for k, v in decision.items() if not k.startswith("_")},
                 usage=usage.to_dict() if hasattr(usage, "to_dict") else usage)

    def play(self):
        last_threats, last_ask_t = None, 0.0
        last_available = set()
        last_reward_click = 0.0
        awaiting_result = False
        unreadable_since = None
        brain_errors = 0
        pending = None
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
                        return "read_error"
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
                    brain_errors = brain_errors + 1 if decision.get("_error") else 0
                    self.apply_decision(decision)
                    pending = None
                    if brain_errors >= 3:
                        return "brain_error"
                    if self.max_decisions and self.decisions >= self.max_decisions:
                        return "max_decisions"

                self.work_queue()

                if pending is None:
                    state = self.snapshot()
                    if not self.readable(state):
                        time.sleep(TICK)
                        continue
                    now_threats = threats(state)
                    now = time.monotonic()
                    since = now - last_ask_t
                    available = affordable(state)
                    can_buy = bool(available) or has_vases(state)
                    plan_done = not self.queue and self.had_plan and can_buy
                    first = last_threats is None
                    new_card = (state.get("conveyor") or state.get("special") == "vases") and bool(
                        available - last_available
                    )
                    # A board change only matters once something can be planted; until
                    # then the player could only answer "wait". The change isn't lost:
                    # last_threats isn't updated, so it still counts when sun arrives.
                    due = since >= MIN_GAP and (first or plan_done or (new_card and not self.queue)
                                                or (important_change(last_threats, now_threats) and can_buy)
                                                or (since >= MAX_GAP and can_buy))
                    # Normal decks can plan ahead for recharge and sun. Empty
                    # conveyors and vases give the player nothing to use.
                    has_usable_deck = any(not s["name"].startswith("unknown") for s in state["seeds"])
                    if not (has_usable_deck or has_vases(state)) or (
                        fruitless >= 3 and since < MAX_GAP and not new_card
                    ):
                        due = False
                    if due:
                        if self.decisions:
                            fruitless = fruitless + 1 if self.planted_since_ask == 0 else 0
                        self.planted_since_ask = 0
                        pending = pool.submit(self.ask_brain, state, list(self.recent), list(self.queue))
                        last_threats, last_ask_t, last_available = now_threats, now, available

                time.sleep(TICK)
        finally:
            # A completed level can have an in-flight decision. Keep it from
            # racing the next level's chooser for the same player's usage.
            pool.shutdown(wait=self.levels > 1 or self.retries > 0, cancel_futures=True)

    def play_levels(self):
        wins = 0
        last_win = None
        retry = False
        retries_left = self.retries
        while wins < self.levels:
            journal = getattr(self, "journal", None)
            if hasattr(self, "brain"):
                self.brain.plan = None       # written fresh for every attempt
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
                if journal:
                    self.brain.notes = journal.prompt_block(situation)
                if self.brain.plan is None and info.get("special") != "whack":
                    self.write_plan(label)
                reset_brain = getattr(self.brain, "reset", None)
                if reset_brain:
                    reset_brain()  # fresh conversation per level, with this level's journal and plan
            self.recorder = LevelRecorder(label, getattr(self, "loadout", []))
            if getattr(self, "loadout_warning", False):
                self.recorder.events.append("before the level: the game warned that your loadout "
                                            "had no sun-producing plant; you started anyway")
                self.loadout_warning = False
            result = self.play()
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
        self.show(f"AI ({self.brain.name}) is taking over. Ctrl+C to stop.")
        self.log(kind="start", brain=self.brain.name, version=self.reader.version)
        outcome, wins = "stopped", 0
        try:
            self.ctl.wake()
            if self.restart:
                self.restart_level()
            outcome, wins = self.play_levels()
            messages = {"won": f"Completed {wins} level(s).",
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
            self.show("Stopped by you.")
            if self.reader.scene() == "playing" and self.reader.board():
                self.ctl.pause()
        except pyautogui.FailSafeException:
            self.show("Stopped: mouse hit a screen corner (fail-safe).")
        finally:
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
    ap.add_argument("--no-journal", action="store_true",
                    help="don't read or write the player's lessons journal (journal/lessons.json)")
    ap.add_argument("--journal-dir", metavar="DIR",
                    help="keep the journal in DIR instead of journal/ (e.g. one per model)")
    args = ap.parse_args()
    if not 1 <= args.levels <= 50 or args.retries < 0 or (
        args.until_level is not None and not 1 <= args.until_level <= 50
    ):
        ap.error("level limits must be 1 through 50 and --retries must be nonnegative")
    try:
        brain = make_brain(args.brain)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Couldn't start the {args.brain} brain: {e}")
    Agent(brain, max_decisions=args.max_decisions, auto_sun=not args.no_auto_sun,
          restart=args.restart, levels=50 if args.until_level else args.levels, retries=args.retries,
          until_level=args.until_level or 50, journal=not args.no_journal,
          journal_dir=args.journal_dir).run()


if __name__ == "__main__":
    main()
