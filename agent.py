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
from brains import make_brain, x_to_col
from controller import Controller

ROOT = Path(__file__).parent
TICK = 0.15                # main loop period (sun pickup, plan execution)
MIN_GAP = 2.0              # never start a new AI request sooner than this after the last one
MAX_GAP = 30.0             # re-plan at least this often while something is affordable
MAX_ACTIONS = 5            # length of the AI's build queue
UPGRADES = {"gatling_pea": "repeater", "twin_sunflower": "sunflower", "gloom_shroom": "fume_shroom",
            "cattail": "lily_pad", "winter_melon": "melon_pult", "gold_magnet": "magnet_shroom",
            "spikerock": "spikeweed", "cob_cannon": "kernel_pult"}


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
    if not (0 <= row < O.ROWS and 0 <= col < O.COLS):
        return "reject", f"cell ({row},{col}) is off the lawn", None
    occupant = state["grid"][row][col]
    stacked = {(p["row"], p["col"]) for p in state["plants"] if p["type"] == "pumpkin"}
    cells = state.get("cells")
    if kind == "plant" and cells and cells[row][col] == O.CELL_DIRT:
        return "reject", f"({row},{col}) is bare dirt - nothing can be planted there", None

    if kind == "shovel":
        if occupant is None and (row, col) not in stacked:
            return "reject", f"nothing to shovel at ({row},{col})", None
        return "ok", "ok", None

    if kind == "plant":
        name = (action.get("seed") or "").strip().lower().replace(" ", "_").replace("-", "_")
        seed = next((s for s in state["seeds"] if s["name"] == name), None)
        if seed is None:
            have = ", ".join(s["name"] for s in state["seeds"])
            return "reject", f"you don't have {name!r} (you have: {have})", None
        if name == "pumpkin":
            if (row, col) in stacked:
                return "reject", f"({row},{col}) already has a pumpkin", None
        elif name in UPGRADES:
            if occupant != UPGRADES[name]:
                return "reject", f"{name} must go on top of a {UPGRADES[name]}", None
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


def threats(state):
    """A zombie arriving in a new row/zone, a plant being eaten, a mower being used."""
    zs = [z for z in state["zombies"] if z["x"] < 760]
    return (
        frozenset((z["row"], z["type"], 0 if x_to_col(z["x"]) >= 5 else 1) for z in zs),
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
    def __init__(self, brain, max_decisions=None, auto_sun=True, restart=False):
        self.ctl = Controller(move_duration=0.08)
        if not self.ctl.reader:
            sys.exit("Can't read game memory. Is Plants vs. Zombies running? (run as admin if needed)")
        self.reader = self.ctl.reader
        self.brain = brain
        self.max_decisions = max_decisions
        self.auto_sun = auto_sun
        self.restart = restart
        self.recent = []
        self.queue = []          # the AI's current plan, carried out as sun allows
        self.had_plan = False
        self.planted_since_ask = 0
        self.board_at_start = None
        self.decisions = 0
        (ROOT / "logs").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = ROOT / "logs" / f"run_{stamp}_{brain.name}.jsonl"
        self.overlay = ROOT / "overlay.txt"

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
        if self.reader.paused(self.reader.board()):
            self.ctl.resume()

    def snapshot(self):
        s = self.reader.snapshot()
        if s.get("errors"):
            self.log(kind="read_error", errors=s["errors"])
        return s

    # --- before the level ----------------------------------------------------
    def restart_level(self):
        """Menu -> Restart Level -> Restart."""
        self.show("Restarting the level...")
        self.ensure_focus()
        self.ctl.click(740, 12)    # Menu
        time.sleep(1.0)
        self.ctl.click(397, 356)   # Restart Level
        time.sleep(1.0)
        self.ctl.click(303, 394)   # Restart (confirm)
        time.sleep(2.5)

    def get_to_playing(self, timeout=90):
        """Click through Crazy Dave, let the AI pick plants, wait for 'Ready, Set, Plant!'."""
        import seed_select
        deadline = time.time() + timeout
        picked = False
        idle_since = time.time()
        while time.time() < deadline:
            scene = self.reader.scene()
            if scene == "playing":
                return True
            if scene == "award":                   # "You got a new plant!" -> Next Level!
                self.ctl.focus()
                self.ctl.click(402, 520)
                time.sleep(3)
                continue
            if scene == "menu":                    # main menu -> Start/continue Adventure
                self.ctl.focus()
                self.ctl.click(565, 130)
                time.sleep(4)
                continue
            if scene == "intro" and not picked and time.time() - idle_since > 10 \
                    and not self.reader.dave_talking() and not seed_select.in_chooser(self.ctl):
                self.ctl.click(400, 300)           # skip the first-time opening cinematic
                idle_since = time.time()
            if scene == "intro":
                if self.reader.dave_talking():
                    self.ctl.focus()
                    self.ctl.click(430, 120)       # "Click to continue"
                    time.sleep(1.2)
                    idle_since = time.time()
                    continue
                if not picked and seed_select.in_chooser(self.ctl):
                    time.sleep(1.5)                # bank refill animation
                    self.choose_plants()
                    picked = True
                    continue
            time.sleep(0.5)
        return False

    def choose_plants(self):
        import seed_select
        self.show("Choosing plants...")
        t0 = time.time()
        names, why = seed_select.choose(self.ctl, self.brain, log=print)
        self.show(f"Loadout: {', '.join(names)}. {why}")
        self.log(kind="seed_pick", seeds=names, reasoning=why, think_seconds=round(time.time() - t0, 1))

    # --- during the level ----------------------------------------------------
    def collect(self):
        """Pick up sun and money. Runs every tick, whatever the AI is doing."""
        for coin in self.reader.coins(self.reader.board()):
            if (coin["type"] in O.SUN_TYPES or coin["type"] in O.MONEY_TYPES) \
                    and 0 <= coin["x"] < 800 and 0 <= coin["y"] < 600:
                self.ctl.click(coin["x"], coin["y"])

    def perform(self, action, seed):
        """Click one action; retry once (after re-focusing the game) if it didn't take."""
        for _ in range(2):
            before = len(self.snapshot().get("plants", []))
            if action["type"] == "plant":
                self.ctl.plant(seed["slot"], action["row"], action["col"])
            else:
                self.ctl.shovel(action["row"], action["col"])
            time.sleep(0.2)
            after = len(self.snapshot().get("plants", []))
            if (after > before) if action["type"] == "plant" else (after < before):
                return True
            self.ensure_focus()
        return False

    def work_queue(self):
        """Carry out queued actions in order, each as soon as it's possible."""
        while self.queue:
            state = self.snapshot()
            if not state.get("in_level"):
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
                ok = self.perform(action, seed)
                self.planted_since_ask += ok
                result = f"{'OK' if ok else 'FAILED (click did not register)'} {desc}"
            print("    " + result)
            self.recent = (self.recent + [result])[-20:]
            self.log(kind="action", action=action, result=result)

    def level_result(self, state):
        """'won' / 'lost' only when the game confirms it; one odd reading isn't enough."""
        scene = self.reader.scene()
        if scene in ("zombies_won", "award"):
            time.sleep(1.0)
            if self.reader.scene() == scene:
                self.log(kind="level_end", reason=f"scene={scene}", wave=state.get("wave"))
                return "lost" if scene == "zombies_won" else "won"
            self.log(kind="odd_scene_reading", scene=scene)
            return None
        if state.get("awards"):
            award = state["awards"][0]
            wave_now, wave_total = state.get("wave", [0, 0])
            self.ctl.click(award["x"], award["y"])
            # The last zombie of the last wave drops the reward; clicking it ends the level
            # (the "level complete" animation takes several seconds before the screen changes).
            if wave_total and wave_now >= wave_total and not state["zombies"]:
                self.log(kind="level_end", reason=f"final reward (type {award['type']}) clicked",
                         wave=state.get("wave"))
                return "won"
            for _ in range(30):
                time.sleep(0.5)
                if self.reader.scene() != "playing" or self.reader.board() != self.board_at_start:
                    self.log(kind="level_end", reason=f"reward type {award['type']} clicked")
                    return "won"
            self.log(kind="not_a_reward", coin=award)
        return None

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
        self.queue = [a for a in decision.get("actions", []) if a.get("type") in ("plant", "shovel")]
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
        pending = None
        fruitless = 0            # AI plans in a row where nothing could be planted
        self.board_at_start = self.reader.board()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            while True:
                # Only ever play the level we started: stop if the game moved on
                # (next level's intro, menu, a restarted board...).
                scene = self.reader.scene()
                if scene != "playing" or self.reader.board() != self.board_at_start:
                    time.sleep(1.0)  # ignore a one-off odd reading
                    if self.reader.scene() != "playing" or self.reader.board() != self.board_at_start:
                        self.log(kind="level_end", reason=f"game left the level (scene={self.reader.scene()})")
                        return {"zombies_won": "lost", "award": "won"}.get(self.reader.scene(), "left")
                self.ensure_focus()
                state = self.snapshot()
                if not state.get("in_level"):
                    time.sleep(TICK)
                    continue

                result = self.level_result(state)
                if result:
                    return result

                if self.auto_sun:
                    self.collect()

                if pending is not None and pending.done():
                    self.apply_decision(pending.result())
                    pending = None
                    if self.max_decisions and self.decisions >= self.max_decisions:
                        return "max_decisions"

                self.work_queue()

                if pending is None:
                    state = self.snapshot()
                    now_threats = threats(state)
                    since = time.time() - last_ask_t
                    can_buy = bool(affordable(state))
                    plan_done = not self.queue and self.had_plan and can_buy
                    first = last_threats is None
                    due = since >= MIN_GAP and (first or plan_done
                                                or important_change(last_threats, now_threats)
                                                or (since >= MAX_GAP and can_buy))
                    # Don't burn calls on a board the AI can't act on.
                    seeds_unreadable = not state.get("seeds") or any(
                        s["name"].startswith("unknown") for s in state["seeds"])
                    if seeds_unreadable or (fruitless >= 3 and since < MAX_GAP):
                        due = False
                    if due:
                        if self.decisions:
                            fruitless = fruitless + 1 if self.planted_since_ask == 0 else 0
                        self.planted_since_ask = 0
                        pending = pool.submit(self.ask_brain, state, list(self.recent), list(self.queue))
                        last_threats, last_ask_t = now_threats, time.time()

                time.sleep(TICK)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # don't wait for a slow AI answer

    def run(self):
        self.show(f"AI ({self.brain.name}) is taking over. Ctrl+C to stop.")
        self.log(kind="start", brain=self.brain.name, version=self.reader.version)
        outcome = "stopped"
        try:
            self.ctl.wake()
            if self.restart:
                self.restart_level()
            if self.reader.scene() != "playing" and not self.get_to_playing():
                self.show(f"Couldn't get into the level (game screen: {self.reader.scene()}).")
                return
            self.show("Level started!")
            outcome = self.play()
            messages = {"won": "LEVEL COMPLETE! The AI won.",
                        "lost": "The zombies ate the AI's brains. Level lost.",
                        "left": "The level was closed.",
                        "max_decisions": f"Stopped after {self.decisions} decisions (--max-decisions)."}
            self.show(messages.get(outcome, outcome))
        except KeyboardInterrupt:
            self.show("Stopped by you.")
            self.ctl.pause()
        except pyautogui.FailSafeException:
            self.show("Stopped: mouse hit a screen corner (fail-safe).")
        finally:
            self.log(kind="stop", outcome=outcome, decisions=self.decisions)
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
    args = ap.parse_args()
    try:
        brain = make_brain(args.brain)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Couldn't start the {args.brain} brain: {e}")
    Agent(brain, max_decisions=args.max_decisions, auto_sun=not args.no_auto_sun,
          restart=args.restart).run()


if __name__ == "__main__":
    main()
