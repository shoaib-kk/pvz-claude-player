"""
Brains decide what to do. Each one takes a game snapshot (from state.py) and
returns a decision dict:

    {"reasoning": "short explanation",
     "actions": [{"type": "plant", "seed": "sunflower", "row": 2, "col": 0},
                 {"type": "shovel", "row": 1, "col": 4},
                 {"type": "wait"}]}

ClaudeBrain  - asks Claude (needs an API key, costs money per decision).
SimpleBrain  - a dumb rule-based player. No key needed; used to test the loop.
"""

import json
import os

import offsets as O
import plant_info
from sun_accounting import MECHANICS_AND_EVIDENCE, accounting_lines

# ---------------------------------------------------------------------------
# Turning game state into text a model can read
# ---------------------------------------------------------------------------

def x_to_col(x):
    """Zombie x -> approximate lawn column (can be <0 or >8).
    A zombie's body is ~50px right of its x; the lawn starts at x=40 with 80px columns."""
    return int((x + 50 - 40) // 80)


SHOOTERS = {"peashooter", "snow_pea", "repeater", "gatling_pea", "threepeater", "split_pea",
            "cactus", "starfruit", "puff_shroom", "scaredy_shroom", "fume_shroom", "gloom_shroom",
            "cabbage_pult", "kernel_pult", "melon_pult", "winter_melon", "sea_shroom", "cattail"}


# Shooters that can hit something in another direction than straight toward the street.
NOT_FORWARD_ONLY = {"split_pea", "starfruit", "cattail"}


def can_hit_col(plant, plant_col, zombie_col):
    """Can this attacker hit a zombie at zombie_col? Straight shooters and lobbers fire toward the
    street (higher columns) only; a zombie standing on the plant's own tile still gets hit."""
    return plant in NOT_FORWARD_ONLY or zombie_col >= plant_col


def shot_behind_zombies(state, row, col, plant):
    """True when a forward-only attacker at (row, col) has zombies in its row but all of them are
    already past it (closer to the house), so none of its shots can reach them."""
    if plant not in SHOOTERS or plant in NOT_FORWARD_ONLY:
        return False
    cols = [x_to_col(z["x"]) for z in state.get("zombies", [])
            if z.get("row") == row and z["x"] < 820 and z.get("type") != "dr_zomboss"]
    return bool(cols) and all(not can_hit_col(plant, col, zc) for zc in cols)


def _row_summary(state, zombies):
    """One line per row: attackers, how many can reach the closest zombie, mower, closest zombie."""
    out = ["", "Row summary (attackers = plants in the row that shoot or lob; "
               "'can hit' = attackers at or left of the closest zombie):"]
    mowers = state.get("mowers", [])
    types = state.get("cells")
    for r, row in enumerate(state["grid"]):
        if types and all(t == O.CELL_DIRT for t in types[r]):
            continue
        attackers = [(c, p) for c, p in enumerate(row) if p in SHOOTERS]
        cols = [x_to_col(z["x"]) for z in zombies if z.get("row") == r]
        mower = "mower ready" if r < len(mowers) and mowers[r] else "no mower"
        if cols:
            closest = min(cols)
            hit = sum(can_hit_col(p, c, closest) for c, p in attackers)
            out.append(f"  row {r}: {len(attackers)} attackers ({hit} can hit the closest zombie), "
                       f"{mower}, {len(cols)} zombies, closest at col {closest}")
        else:
            out.append(f"  row {r}: {len(attackers)} attackers, {mower}, no zombies")
    return out


def action_text(action):
    target = f"({action.get('row')},{action.get('col')})"
    if action["type"] == "plant":
        return f"plant {action.get('seed')} at {target}"
    return f"{action['type']} at {target}"


def describe(state, recent, queue=None, known_plants=(), *, compact=False):
    """Compact text description of the board for the model."""
    lines = []
    wave_now, wave_total = state.get("wave", [0, 0])
    lines.append(f"Sun: {state['sun']}    Wave: {wave_now}/{wave_total}"
                 + (f"    Sun collected in the last minute: {state['sun_per_min']}"
                    if state.get("sun_per_min") is not None else ""))
    terrain = state.get("terrain", "day")
    special = state.get("special")
    rules = {
        "night": "There is no falling sun. Mushrooms are awake. Graves need Grave Busters.",
        "pool": "Rows 2 and 3 are water. Zombies come down the water rows too. A land plant in a water cell "
                "needs a lily_pad in that cell first (two actions: lily_pad at (r,c), then the plant at (r,c)). "
                "Potato Mines and Spikeweeds can't go in water. Aquatic plants need open water.",
        "fog": "Rows 2 and 3 are water. A land plant in a water cell needs a lily_pad in that cell first "
               "(two actions). Mushrooms are awake and there is no falling sun.",
        "roof": "Plants need a Flower Pot first. The roof slopes, so straight shots hit the slope; lobbed shots don't.",
        "boss": "Roof: plants need Flower Pots. Dr. Zomboss rolls fireballs and iceballs down rows "
                "(an Ice-shroom puts out a fireball, a Jalapeno melts an iceball) and lowers his head to attack.",
    }
    lines.append(f"Terrain: {terrain}. " + rules.get(terrain, ""))
    if state.get("conveyor"):
        lines.append("Conveyor cards are free and single-use; a full belt stops receiving new cards. "
                     "Only the cards listed below exist.")
    if special == "bowling":
        lines.append("Wall-nut Bowling: nuts can only be launched from columns 0, 1, or 2 (house side of the red line). "
                     "A launched Wall-nut rolls right, damages zombies it hits and bounces into a neighbouring row; "
                     "it leaves its launch cell immediately, so the cell can be reused. Explode-o-nuts explode "
                     "on contact. There are no other plants.")
    elif special == "vases":
        lines.append("Vasebreaker: use break_vase to smash a vase, starting near the right edge. "
                     "Use its temporary seed packets before they expire. Open one at a time.")
    lines.append("")
    lines.append("Seeds (slot: name, sun, status):")
    for s in state["seeds"]:
        if s["ready"]:
            status = "READY"
        elif state.get("conveyor"):
            status = "moving into view"
        else:
            now, full = (s.get("recharge") or [0, 0])[:2]
            left = max(0, (full - now)) / 100 if full else 0
            status = f"recharging, ready in {left:.0f}s" if left else "recharging"
        afford = "" if s["cost"] is None or s["cost"] <= state["sun"] else " (can't afford)"
        lines.append(f"  {s['slot']}: {s['name']}, {s['cost']} sun, {status}{afford}")
    lines.extend(accounting_lines(state, queue))
    known = plant_info.describe_plants([s["name"] for s in state["seeds"] if s["name"] not in known_plants],
                                       state.get("level"))
    if known:
        lines.append("")
        lines.append("What you know about these plants"
                     + (" (from your Almanac):" if plant_info.stage(state.get("level")) == "almanac" else ":"))
        lines.extend(known)
    lines.append("")
    if compact:
        lines.append("Lawn: rows top to bottom, columns 0-8 house to street. "
                     ". empty, # dirt, M mower, % plant health, Z:name zombie in that cell, "
                     ">> zombies still beyond col 8.")
    else:
        lines.append("Lawn (row 0 = top, col 0 = next to the house, zombies walk from col 8 toward col 0).")
        lines.append("Each cell: plant name, '.' = empty grass, '#' = bare dirt (can't plant there).")
        lines.append("'M' at the start of a row = lawn mower still available. "
                     "(N%) = a damaged plant's remaining health. 'Z:name' = a zombie in that cell; "
                     "'>> name' after a row = zombies still beyond col 8.")
    lawn_zombies = {}
    for z in state["zombies"]:
        if z["x"] < 820 and z.get("type") != "dr_zomboss":
            lawn_zombies.setdefault((z.get("row"), max(0, x_to_col(z["x"]))), []).append(z["type"])
    stacked = {}
    for p in state["plants"]:
        if p["type"] in ("pumpkin", "lily_pad", "flower_pot"):
            stacked.setdefault((p["row"], p["col"]), []).append(p["type"])
    items = {(i["row"], i["col"]): i["type"] for i in state.get("items", [])}
    sleeping = {(p["row"], p["col"]) for p in state["plants"] if p.get("asleep")}
    notes = {}
    for p in state["plants"]:
        if p["type"] in ("lily_pad", "flower_pot"):
            continue
        tags = []
        health = plant_info.plant_health(p["type"], p.get("hp"))
        if health is not None and health < 90:
            tags.append(f"{health}%")
        if p["type"] == "potato_mine" and p.get("age") is not None:
            tags.append("armed" if p["age"] >= plant_info.POTATO_MINE_ARM_SECONDS
                        else f"arming {plant_info.POTATO_MINE_ARM_SECONDS - p['age']:.0f}s")
        if tags:
            notes[(p["row"], p["col"])] = "(" + ", ".join(tags) + ")"
    types = state.get("cells")
    for r, row in enumerate(state["grid"]):
        if types and all(t == O.CELL_DIRT for t in types[r]):
            lines.append(f"  row {r}   | (bare dirt - unusable this level)")
            continue
        mower = "M" if state.get("mowers", [True] * len(state["grid"]))[r] else "-"
        cells = []
        for c, plant in enumerate(row):
            cell = types[r][c] if types else O.CELL_GRASS
            name = plant or items.get((r, c)) or {0: "#", O.CELL_DIRT: "#", O.CELL_POOL: "water"}.get(cell, ".")
            if plant and (r, c) in sleeping:
                name += "(asleep)"
            if plant and (r, c) in notes:
                name += notes[(r, c)]
            if (r, c) in stacked:
                name = "+".join(stacked[(r, c)] + ([name] if plant else []))
            for zname in lawn_zombies.get((r, c), []):
                name += f" Z:{zname}"
            cells.append(name)
        beyond = [n for (zr, zc), names in sorted(lawn_zombies.items()) if zr == r and zc > 8 for n in names]
        tail = ("  >> " + ", ".join(beyond)) if beyond else ""
        if compact:
            lines.append(f"  row {r} {mower}: " + "|".join(cells) + tail)
        else:
            lines.append(f"  row {r} {mower} | " + " | ".join(cells) + tail)
    lines.append("")
    zs = [z for z in state["zombies"] if z["x"] < 820 or z["type"] == "dr_zomboss"]
    if zs:
        lines.append("Zombies on the lawn (closest first):")
        for z in zs:
            armor = f", armor {z['armor_hp']}" if z["armor_hp"] else ""
            if z["type"] == "dr_zomboss":
                lines.append(f"  Dr. Zomboss: hp {z['hp']}, phase {z.get('phase', 'unknown')}")
                if ball := z.get("projectile"):
                    lines.append(f"  Incoming {ball['type']} ball in row {ball['row']}")
                continue
            lines.append(f"  {z['type']} in row {z['row']} at about col {x_to_col(z['x'])} "
                         f"(x={z['x']}), hp {z['hp']}{armor}")
    else:
        lines.append("No zombies on the lawn yet.")
    known_z = plant_info.describe_zombies([z["type"] for z in zs], state.get("level"))
    if known_z:
        lines.append("What you know about these zombies:")
        lines.extend(known_z)
    if not special:
        lines.extend(_row_summary(state, zs))
    if queue:
        lines.append("")
        lines.append("Your unfinished queue (keep, append, cancel IDs, or replace):")
        for a in queue:
            policy = "independent" if a.get("independent") else "ordered"
            group = f", group {a['group']}" if a.get("group") else ""
            lines.append(f"  #{a.get('id', '?')} {action_text(a)}, {policy}{group}")
    if state.get("execution"):
        lines += ["", state["execution"]]
    if recent:
        lines.append("")
        lines.append("Results of your recent actions, and things that happened:")
        lines.extend(f"  {r}" for r in dict.fromkeys(recent[-8:]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are playing Plants vs. Zombies. You get the current board and control your build queue.
Give a short reasoning sentence, edit, and up to 5 actions (15 pending maximum).

Actions:
- plant: put a seed from your seed packets on an empty cell.
- shovel: remove one of your plants to free its cell (you get no sun back).
- break_vase: click a vase at the specified row and column in Vasebreaker.

How your plan is carried out:
- The game keeps running while you think (a few seconds), so zombies will have moved a little
  by the time your plan starts. Plan slightly ahead.
- edit="keep": leave the queue alone; actions=[]. edit="append": add actions at the end.
  edit="cancel": cancel the IDs in cancel=[...]; actions=[]. edit="replace": supply the new queue.
- Existing queue actions have IDs. When retaining one in a replacement, copy its id and move.
  Finished IDs never run again. To request a new move, omit id. Missing edit defaults to replace.
- Actions are ordered by default: they wait for earlier actions, sun, and seed recharge.
  Set independent=true on an action to let it run even while earlier actions wait.
- Optionally give adjacent actions the same positive group number and independent value.
  A group waits for all its steps to be legal, funded, and ready, then runs in order. No supports
  or partners are added automatically. A group cannot use the same recharging packet twice.
  Grouping is a readiness check, not a guarantee: a live change can interrupt the remaining steps.
  Canceling one member cancels its group. Group numbers are local to this answer.
- You are asked again when the plan is used up, or when something important happens
  (a zombie shows up in a new place, you lose a plant, a lawn mower is used).
- To wait with no pending actions, use replace with actions=[].

Game rules:
- Sun is collected for you automatically. Plants cost sun; seeds recharge after use.
- Zombies walk along their row toward the house (col 0) and eat plants in their way.
- Shooting and lobbing plants fire toward the street (higher columns) only, unless their
  description says otherwise. They can't hit a zombie in a lower column than their own: once a zombie
  has walked past a plant, that plant can no longer hurt it.
- Each row has one lawn mower. It fires by itself when a zombie reaches the house end of the row,
  clears that row, and is gone. A zombie that reaches the house in a row with no mower loses the game.
- Plants can't be moved; the shovel removes one (no sun back).
- Zombies come in waves; flag waves are larger. Survive the last wave to win.
- Upgrade plants go on top of their base plant: gatling_pea on repeater, twin_sunflower on sunflower,
  winter_melon on melon_pult, spikerock on spikeweed, cob_cannon on the left of two side-by-side kernel_pults.
- Each action is checked before it runs; invalid ones are rejected and you will see why next turn.
- What you know about each plant is listed with the board. How to use them is up to you;
  your journal (if any) holds lessons you wrote after earlier levels.

Answer with JSON only. Explain your plan in one short sentence for the viewer."""

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "edit": {"type": "string", "enum": ["keep", "append", "cancel", "replace"]},
        "cancel": {"type": "array", "items": {"type": "integer"}, "maxItems": 15},
        "actions": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["plant", "shovel", "break_vase"]},
                    "seed": {"type": "string"},
                    "row": {"type": "integer"},
                    "col": {"type": "integer"},
                    "id": {"type": "integer"},
                    "independent": {"type": "boolean"},
                    "group": {"type": "integer", "minimum": 0},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reasoning", "edit", "actions"],
    "additionalProperties": False,
}


PICK_SYSTEM = """You are about to play a level of Plants vs. Zombies and must choose your plants.
Facts: in pool/fog levels, rows 2 and 3 are water. Aquatic plants (lily_pad, sea_shroom, tangle_kelp...)
go directly on water; any other plant needs a Lily Pad under it there.
On the roof every plant needs a Flower Pot. Night and fog levels take place at night: there is no
falling sun and mushrooms are awake. In day, pool and roof levels mushrooms sleep unless woken by a
Coffee Bean. Falling sun is collected for you automatically.
Upgrade plants (gatling_pea, gold_magnet, cob_cannon...) can only be planted on top of their base
plant, so they need that base plant in the loadout too.
Pick exactly the number of plants asked for, using only names from the list.
Your journal (if any) holds lessons you wrote after earlier levels.
Also write your game plan for this level in "plan": 3-6 short lines covering your sun economy,
which plants go in which columns, how you'll handle the previewed zombies, and what you'll do
if a row starts to break. You'll see this plan with every board during the level.
Answer with JSON only; keep "reasoning" to one or two short sentences
explaining your loadout - it may be shown to viewers."""

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "seeds": {"type": "array", "items": {"type": "string"}},
        "plan": {"type": "string"},
    },
    "required": ["reasoning", "seeds", "plan"],
    "additionalProperties": False,
}


PLAN_SYSTEM = """You are about to play a level of Plants vs. Zombies. The level is starting and this is the
first board. Before you make any moves, write your game plan for the level in "plan": 3-6 short lines
covering your sun economy, which plants go in which columns, how you'll handle the zombies you
expect, and what you'll do if a row starts to break. You'll see this plan with every board during
the level. Your journal (if any) holds lessons you wrote after earlier levels.
Answer with JSON only."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {"plan": {"type": "string"}},
    "required": ["plan"],
    "additionalProperties": False,
}


def pick_prompt(options, slots, zombies, forced=None, terrain="day", level=None):
    lines = [f"Terrain: {terrain}. Choose exactly {slots} plants (list {slots} names)."]
    if forced:
        lines += [f"Crazy Dave has already locked these into your loadout (you will have them too): "
                  + ", ".join(forced)]
    lines += ["", "Available plants (name: sun cost):"]
    lines += [f"  {o['name']}: {o['cost']}" for o in options]
    known = plant_info.describe_plants([o["name"] for o in options] + list(forced or []), level)
    if known:
        lines += ["", "What you know about them"
                  + (" (from your Almanac):" if plant_info.stage(level) == "almanac" else ":")]
        lines += known
    if zombies:
        lines += ["", "Zombies previewed for this level: "
                  + ", ".join(f"{n} x{k}" for n, k in zombies.items())]
        lines += plant_info.describe_zombies(list(zombies), level)
    return "\n".join(lines)


class Notes:
    """Per-run knowledge the agent hands the player: its journal text, the current level,
    and the game plan the player wrote for this level."""
    notes = ""
    level = None
    plan = None
    plan_effort = None     # effort for the few strategic calls: pick + plan, plan, reflection
    knowledge = ""         # this level's plant facts, sent once in the (cached) system prompt
    known_plants = ()      # ...so the boards can leave them out

    def set_loadout(self, names, level):
        """Put the plant facts for a fixed loadout into the system prompt for this level."""
        lines = plant_info.describe_plants(names, level)
        self.known_plants = tuple(names) if lines else ()
        self.knowledge = ("\n\nWhat you know about your plants this level"
                          + (" (from your Almanac):\n" if plant_info.stage(level) == "almanac" else ":\n")
                          + "\n".join(lines)) if lines else ""

    def system(self, base):
        text = base + MECHANICS_AND_EVIDENCE + (self.knowledge or "") + (self.notes or "")
        if self.plan:
            text += ("\n\nYour game plan for this level (you wrote it before the level started; "
                     "follow it unless the board shows it isn't working):\n" + self.plan.strip())
        return text

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        self.last_options = [o["name"] for o in options]    # logged with the pick
        answer = self.ask(self.system(PICK_SYSTEM),
                          pick_prompt(options, slots, zombies, forced, terrain, self.level),
                          PICK_SCHEMA, effort=self.plan_effort)
        self.plan = (answer.get("plan") or "").strip() or None
        return answer

    def write_plan(self, state):
        answer = self.ask(self.system(PLAN_SYSTEM), describe(state, []), PLAN_SCHEMA,
                          effort=self.plan_effort)
        self.plan = (answer.get("plan") or "").strip() or None
        return self.plan


class ClaudeBrain(Notes):
    name = "claude"

    def __init__(self, model="claude-opus-5-5", effort="medium"):
        import anthropic  # imported here so SimpleBrain works without the package
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (or an `ant auth login` profile)
        self.model = model
        self.effort = effort
        self.last_usage = None

    def ask(self, system, user, schema, effort=None):
        self.last_usage = None
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort or self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            # If a request is ever declined, the API retries it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        self.last_usage = response.usage
        if response.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"no answer (stop_reason={response.stop_reason})")
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)

    def decide(self, state, recent, queue=None):
        self.last_usage = None
        board = describe(state, recent, queue, self.known_plants, compact=True)
        decision = self.ask(self.system(SYSTEM_PROMPT), board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision



# ---------------------------------------------------------------------------
# Claude through Claude Code (uses your Claude Pro/Max subscription, no API key)
# ---------------------------------------------------------------------------

def find_claude_exe():
    """The real claude.exe (calling the .cmd wrapper would mangle JSON arguments)."""
    import shutil
    candidates = [
        os.path.expandvars(r"%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"),
        shutil.which("claude.exe") or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError("claude.exe not found. Install it: npm install -g @anthropic-ai/claude-code")


PERSISTENT_NOTE = ("\n\nYou will receive a new board after every plan in this conversation. "
                   "Only the latest board and queue are current; earlier ones are out of date.")


class ClaudeCodeBrain(Notes):
    """Sends each board to headless Claude Code and reads back JSON.
    Uses the account you logged in with (`claude auth login`), so it counts
    toward your subscription's usage limits instead of costing API money.

    Gameplay decisions go to one long-running `claude -p --input-format stream-json`
    process, so the CLI start-up (~3-6 s) is paid once per level instead of per decision.
    The conversation is reset at each level start and every `max_turns` decisions so
    the context stays small. Seed picks (once per level) use a one-shot call."""
    name = "subscription"

    def __init__(self, model=None, effort="medium", timeout=180, persistent=True, max_turns=3):
        if max_turns < 1:
            raise ValueError("PVZ_TURNS_PER_PROCESS must be at least 1")
        self.exe = find_claude_exe()
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.persistent = persistent
        self.max_turns = max_turns
        self.last_usage = None
        self._proc = None
        self._lines = None
        self._turns = 0
        import threading
        self._lock = threading.Lock()
        import atexit
        atexit.register(self.close)

    def _base_cmd(self, system, schema, effort=None):
        cmd = [self.exe, "-p",
               "--json-schema", json.dumps(schema),
               "--system-prompt", system,
               "--tools", "",                 # no file/shell tools: it only answers
               "--setting-sources", "",       # ignore any CLAUDE.md / project settings
               "--strict-mcp-config",         # don't load MCP servers / claude.ai connectors (~3-6 s)
               "--disable-slash-commands",    # don't load skills
               "--settings", '{"alwaysThinkingEnabled": false}',
               "--no-session-persistence",
               "--effort", effort or self.effort]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    # ---- persistent decision process ------------------------------------------------
    def _start(self):
        import subprocess, threading, queue
        cmd = self._base_cmd(self.system(SYSTEM_PROMPT) + PERSISTENT_NOTE, DECISION_SCHEMA)
        cmd += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._lines = queue.Queue()
        proc, lines = self._proc, self._lines

        def pump():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()
        self._turns = 0

    def close(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    def reset(self):
        """Start a fresh conversation (called at each level start). The new process
        boots in the background, so the next decision doesn't pay the start-up."""
        if not self.persistent:
            return
        with self._lock:
            self.close()
            self._start()

    def _ask_persistent(self, user):
        import queue
        with self._lock:
            if self._proc is None or self._proc.poll() is not None or self._turns >= self.max_turns:
                self.close()
                self._start()
            self._turns += 1
            msg = {"type": "user", "message": {"role": "user", "content": user}}
            try:
                self._proc.stdin.write(json.dumps(msg) + "\n")
                self._proc.stdin.flush()
            except OSError as e:
                self.close()
                raise RuntimeError(f"claude process died: {e}")
            while True:
                try:
                    line = self._lines.get(timeout=self.timeout)
                except queue.Empty:
                    self.close()
                    raise RuntimeError("claude did not answer in time")
                if line is None:
                    self.close()
                    raise RuntimeError("claude process exited")
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "result":
                    break
            if self._turns >= self.max_turns:
                # Start the next process now, so its start-up is done before the next decision
                # and the next decision doesn't carry this conversation along.
                self.close()
                self._start()
        return self._parse(data)

    # ---- public API ---------------------------------------------------------------
    def decide(self, state, recent, queue=None):
        self.last_usage = None
        board = describe(state, recent, queue, self.known_plants, compact=True)
        if self.persistent:
            decision = self._ask_persistent(board)
        else:
            decision = self.ask(self.system(SYSTEM_PROMPT), board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision


    def _parse(self, data):
        self.last_usage = data.get("usage")
        if data.get("is_error"):
            raise RuntimeError(str(data.get("result"))[:300])
        answer = data.get("structured_output")
        if answer is None:
            answer = json.loads(data.get("result") or "{}")
        return answer

    def ask(self, system, user, schema, effort=None):
        """One-shot call (new process)."""
        import subprocess
        self.last_usage = None
        cmd = self._base_cmd(system, schema, effort) + ["--output-format", "json"]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                              encoding="utf-8", timeout=self.timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300] or proc.stdout[:300]}")
        return self._parse(data)


# ---------------------------------------------------------------------------
# Simple rule-based player (no API needed)
# ---------------------------------------------------------------------------

ATTACKERS = ["gatling_pea", "repeater", "threepeater", "snow_pea", "peashooter", "split_pea",
             "cactus", "melon_pult", "kernel_pult", "cabbage_pult", "fume_shroom", "puff_shroom",
             "starfruit", "winter_melon"]
INSTANT = ["cherry_bomb", "jalapeno", "squash", "potato_mine"]
WALLS = ["tall_nut", "wall_nut"]


class SimpleBrain(Notes):
    name = "simple"

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        have = [o["name"] for o in options]
        wish = ["sunflower", "peashooter", "repeater", "potato_mine", "wall_nut", "cherry_bomb",
                "snow_pea", "squash", "threepeater", "tall_nut", "jalapeno", "cabbage_pult"]
        if terrain in ("night", "fog"):
            wish = ["sun_shroom", "puff_shroom", "fume_shroom", "grave_buster"] + wish
        if terrain in ("pool", "fog"):
            wish = ["lily_pad", "tangle_kelp"] + wish
        if terrain in ("roof", "boss"):
            wish = ["flower_pot", "sunflower", "cabbage_pult", "kernel_pult"] + wish
        wish = list(dict.fromkeys(wish))
        seeds = [w for w in wish if w in have][:slots]
        return {"reasoning": "Standard sunflower + peas + emergency plants.", "seeds": seeds}

    def decide(self, state, recent, queue=None):
        sun = state["sun"]
        seeds = {s["name"]: s for s in state["seeds"] if s["ready"] and (s["cost"] or 0) <= sun}
        grid = state["grid"]
        if state.get("special") == "bowling":
            nut = next((n for n in ("wall_nut", "explode_o_nut", "giant_wall_nut") if n in seeds), None)
            if nut and state["zombies"]:
                return self._plant(nut, state["zombies"][0]["row"], 0, "Rolling into the nearest threat.")
            return {"reasoning": "Waiting for a target or a nut.", "actions": []}
        if state.get("special") == "vases" and not seeds and not state["zombies"]:
            vases = [i for i in state.get("items", []) if i["type"] == "vase"]
            if vases:
                vase = max(vases, key=lambda i: i["col"])
                return {"reasoning": "Opening a vase near the right edge.",
                        "actions": [{"type": "break_vase", "row": vase["row"], "col": vase["col"]}]}
        empty = lambda r, c: 0 <= c < O.COLS and grid[r][c] is None
        zs = [z for z in state["zombies"] if z["x"] < 800]

        # 1. Emergency: zombie close to the house -> instant kill or potato mine in front of it
        for z in zs:
            col = x_to_col(z["x"])
            if col <= 4:
                for name in INSTANT:
                    if name in seeds:
                        target = max(0, col - 1) if name == "potato_mine" else max(0, min(8, col))
                        if empty(z["row"], target):
                            return self._plant(name, z["row"], target,
                                               f"A {z['type']} is close in row {z['row']}: {name}!")

        # 2. Economy: up to 2 sunflowers per row in the back columns
        flowers = sum(row.count("sunflower") for row in grid)
        if "sunflower" in seeds and flowers < 8:
            for c in (0, 1):
                for r in range(len(grid)):
                    if empty(r, c):
                        return self._plant("sunflower", r, c, "More sunflowers = more sun.")

        # 3. Defence: attacker in the most threatened row that has the fewest attackers
        attacker = next((a for a in ATTACKERS if a in seeds), None)
        if attacker:
            threat = {r: sum(1 for z in zs if z["row"] == r) for r in range(len(grid))}
            defenders = {r: sum(1 for p in grid[r] if p in ATTACKERS) for r in range(len(grid))}
            for r in sorted(range(len(grid)), key=lambda r: (-threat[r], defenders[r])):
                for c in range(2, 6):
                    if empty(r, c):
                        return self._plant(attacker, r, c, f"Adding {attacker} to row {r}.")

        # 4. Walls in front of rows with zombies
        wall = next((w for w in WALLS if w in seeds), None)
        if wall:
            for z in zs:
                if empty(z["row"], 6):
                    return self._plant(wall, z["row"], 6, f"Wall in row {z['row']}.")

        return {"reasoning": "Saving sun.", "actions": [{"type": "wait"}]}

    @staticmethod
    def _plant(seed, row, col, why):
        return {"reasoning": why, "actions": [{"type": "plant", "seed": seed, "row": row, "col": col}]}


def make_brain(name):
    if name == "claude":
        model = os.environ.get("PVZ_MODEL", "claude-opus-5-5")
        effort = os.environ.get("PVZ_EFFORT", "medium")
        brain = ClaudeBrain(model=model, effort=effort)
        brain.plan_effort = os.environ.get("PVZ_PLAN_EFFORT", effort)
        return brain
    if name == "subscription":
        brain = ClaudeCodeBrain(model=os.environ.get("PVZ_MODEL") or None,
                                effort=os.environ.get("PVZ_EFFORT", "medium"),
                                persistent=os.environ.get("PVZ_PERSISTENT", "1") != "0",
                                max_turns=int(os.environ.get("PVZ_TURNS_PER_PROCESS", "3")))
        brain.plan_effort = os.environ.get("PVZ_PLAN_EFFORT", brain.effort)
        return brain
    if name == "simple":
        return SimpleBrain()
    raise ValueError(f"unknown brain {name!r} (use 'subscription', 'claude' or 'simple')")
