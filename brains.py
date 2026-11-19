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


def _row_summary(state, zombies):
    """One line per row: attackers, front blocker, closest zombie. Helps the player spot weak lanes."""
    out = ["", "Row summary (attackers = plants in the row that shoot or lob):"]
    mowers = state.get("mowers", [])
    types = state.get("cells")
    for r, row in enumerate(state["grid"]):
        if types and all(t == O.CELL_DIRT for t in types[r]):
            continue
        shooters = sum(1 for p in row if p in SHOOTERS)
        cols = [x_to_col(z["x"]) for z in zombies if z.get("row") == r]
        near = f"{len(cols)} zombies, closest at col {min(cols)}" if cols else "no zombies"
        mower = "mower ready" if r < len(mowers) and mowers[r] else "no mower"
        out.append(f"  row {r}: {shooters} attackers, {mower}, {near}")
    return out


def describe(state, recent, queue=None):
    """Compact text description of the board for the model."""
    lines = []
    wave_now, wave_total = state.get("wave", [0, 0])
    lines.append(f"Sun: {state['sun']}    Wave: {wave_now}/{wave_total}")
    terrain = state.get("terrain", "day")
    special = state.get("special")
    rules = {
        "night": "There is no falling sun. Mushrooms are awake. Graves need Grave Busters.",
        "pool": "Rows 2 and 3 are water. Lily Pads support dry-land plants there; aquatic plants need open water.",
        "fog": "Rows 2 and 3 are water. Use Lily Pads for dry-land plants. Mushrooms are awake and there is no falling sun.",
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
    lines.append("Seed packets (slot: name, cost, status):")
    for s in state["seeds"]:
        status = "READY" if s["ready"] else "moving into view" if state.get("conveyor") else "recharging"
        afford = "" if s["cost"] is None or s["cost"] <= state["sun"] else " (can't afford)"
        lines.append(f"  {s['slot']}: {s['name']}, {s['cost']} sun, {status}{afford}")
    known = plant_info.describe_plants([s["name"] for s in state["seeds"]], state.get("level"))
    if known:
        lines.append("")
        lines.append("What you know about these plants"
                     + (" (from your Almanac):" if plant_info.stage(state.get("level")) == "almanac" else ":"))
        lines.extend(known)
    lines.append("")
    lines.append("Lawn (row 0 = top, col 0 = next to the house, zombies walk from col 8 toward col 0).")
    lines.append("Each cell: plant name, '.' = empty grass, '#' = bare dirt (can't plant there).")
    lines.append("'M' at the start of a row = lawn mower still available.")
    stacked = {}
    for p in state["plants"]:
        if p["type"] in ("pumpkin", "lily_pad", "flower_pot"):
            stacked.setdefault((p["row"], p["col"]), []).append(p["type"])
    items = {(i["row"], i["col"]): i["type"] for i in state.get("items", [])}
    sleeping = {(p["row"], p["col"]) for p in state["plants"] if p.get("asleep")}
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
            if (r, c) in stacked:
                name = "+".join(stacked[(r, c)] + ([name] if plant else []))
            cells.append(name)
        lines.append(f"  row {r} {mower} | " + " | ".join(cells))
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
    if not special:
        lines.extend(_row_summary(state, zs))
    if queue:
        lines.append("")
        lines.append("Your unfinished plan (will be replaced by your answer):")
        lines.extend(f"  {json.dumps(a)}" for a in queue)
    if recent:
        lines.append("")
        lines.append("Results of your recent actions:")
        lines.extend(f"  {r}" for r in recent[-8:])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are playing Plants vs. Zombies. You get the current board and give a build plan:
an ordered list of up to 5 actions.

Actions:
- plant: put a seed from your seed packets on an empty cell.
- shovel: remove one of your plants to free its cell (you get no sun back).
- break_vase: click a vase at the specified row and column in Vasebreaker.

How your plan is carried out:
- The game keeps running while you think (a few seconds), so zombies will have moved a little
  by the time your plan starts. Plan slightly ahead.
- Actions run strictly in your order. Each one happens as soon as you have enough sun and the seed
  has recharged, so you can queue things you can't afford yet ("save up" = put it next in the plan).
- Your new plan replaces any unfinished old one.
- You are asked again when the plan is used up, or when something important happens
  (a zombie shows up in a new place, you lose a plant, a lawn mower is used).
- An empty plan means: do nothing until something changes.

Game rules:
- Sun is collected for you automatically. Plants cost sun; seeds recharge after use.
- Zombies walk along their row toward the house (col 0) and eat plants in their way.
- Each row has one lawn mower. It fires by itself when a zombie reaches the house end of the row,
  clears that row, and is gone. A zombie that reaches the house in a row with no mower loses the game.
- Plants can't be moved; the shovel removes one (no sun back).
- Zombies come in waves; flag waves are larger. Survive the last wave to win.
- Upgrade plants go on top of their base plant: gatling_pea on repeater, twin_sunflower on sunflower,
  winter_melon on melon_pult, spikerock on spikeweed, cob_cannon on the left of two side-by-side kernel_pults.
- Each action is checked before it runs; invalid ones are rejected and you will see why next turn.
- What you know about each plant is listed with the board. How to use them is up to you;
  your journal (if any) holds lessons you wrote after earlier levels.

Answer with JSON only. Keep "reasoning" to one or two short sentences explaining your plan - it may be shown to viewers."""

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["plant", "shovel", "break_vase"]},
                    "seed": {"type": "string"},
                    "row": {"type": "integer"},
                    "col": {"type": "integer"},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reasoning", "actions"],
    "additionalProperties": False,
}


PICK_SYSTEM = """You are about to play a level of Plants vs. Zombies and must choose your plants.
Facts: in pool/fog levels, rows 2 and 3 are water (only Lily Pads and water plants go there directly).
On the roof every plant needs a Flower Pot. At night and in fog there is no falling sun. Mushrooms
sleep during the day unless woken by a Coffee Bean. Falling sun is collected for you automatically.
Upgrade plants (gatling_pea, gold_magnet, cob_cannon...) can only be planted on top of their base
plant, so they need that base plant in the loadout too.
Pick exactly the number of plants asked for, using only names from the list.
Your journal (if any) holds lessons you wrote after earlier levels.
Answer with JSON only; keep "reasoning" to one or two short sentences
explaining your loadout - it may be shown to viewers."""

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "seeds": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reasoning", "seeds"],
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
    return "\n".join(lines)


class Notes:
    """Per-run knowledge the agent hands the player: its journal text and the current level."""
    notes = ""
    level = None

    def system(self, base):
        return base + (self.notes or "")


class ClaudeBrain(Notes):
    name = "claude"

    def __init__(self, model="claude-opus-5-5", effort="medium"):
        import anthropic  # imported here so SimpleBrain works without the package
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (or an `ant auth login` profile)
        self.model = model
        self.effort = effort
        self.last_usage = None

    def ask(self, system, user, schema):
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
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
        board = describe(state, recent, queue)
        decision = self.ask(self.system(SYSTEM_PROMPT), board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        return self.ask(self.system(PICK_SYSTEM), pick_prompt(options, slots, zombies, forced, terrain, self.level),
                        PICK_SCHEMA)


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
                   "Only the latest board is current; earlier boards are out of date.")


class ClaudeCodeBrain(Notes):
    """Sends each board to headless Claude Code and reads back JSON.
    Uses the account you logged in with (`claude auth login`), so it counts
    toward your subscription's usage limits instead of costing API money.

    Gameplay decisions go to one long-running `claude -p --input-format stream-json`
    process, so the CLI start-up (~3-6 s) is paid once per level instead of per decision.
    The conversation is reset at each level start and every `max_turns` decisions so
    the context stays small. Seed picks (once per level) use a one-shot call."""
    name = "subscription"

    def __init__(self, model=None, effort="medium", timeout=180, persistent=True, max_turns=15):
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

    def _base_cmd(self, system, schema):
        cmd = [self.exe, "-p",
               "--json-schema", json.dumps(schema),
               "--system-prompt", system,
               "--tools", "",                 # no file/shell tools: it only answers
               "--setting-sources", "",       # ignore any CLAUDE.md / project settings
               "--strict-mcp-config",         # don't load MCP servers / claude.ai connectors (~3-6 s)
               "--disable-slash-commands",    # don't load skills
               "--settings", '{"alwaysThinkingEnabled": false}',
               "--no-session-persistence",
               "--effort", self.effort]
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
        return self._parse(data)

    # ---- public API ---------------------------------------------------------------
    def decide(self, state, recent, queue=None):
        board = describe(state, recent, queue)
        if self.persistent:
            decision = self._ask_persistent(board)
        else:
            decision = self.ask(self.system(SYSTEM_PROMPT), board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        return self.ask(self.system(PICK_SYSTEM), pick_prompt(options, slots, zombies, forced, terrain, self.level),
                        PICK_SCHEMA)

    def _parse(self, data):
        if data.get("is_error"):
            raise RuntimeError(str(data.get("result"))[:300])
        self.last_usage = data.get("usage")
        answer = data.get("structured_output")
        if answer is None:
            answer = json.loads(data.get("result") or "{}")
        return answer

    def ask(self, system, user, schema):
        """One-shot call (new process)."""
        import subprocess
        cmd = self._base_cmd(system, schema) + ["--output-format", "json"]
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
        return ClaudeBrain(model=model, effort=effort)
    if name == "subscription":
        return ClaudeCodeBrain(model=os.environ.get("PVZ_MODEL") or None,
                               effort=os.environ.get("PVZ_EFFORT", "medium"),
                               persistent=os.environ.get("PVZ_PERSISTENT", "1") != "0")
    if name == "simple":
        return SimpleBrain()
    raise ValueError(f"unknown brain {name!r} (use 'subscription', 'claude' or 'simple')")
