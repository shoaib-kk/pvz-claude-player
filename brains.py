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

# ---------------------------------------------------------------------------
# Turning game state into text a model can read
# ---------------------------------------------------------------------------

def x_to_col(x):
    """Zombie x -> approximate lawn column (can be <0 or >8).
    A zombie's body is ~50px right of its x; the lawn starts at x=40 with 80px columns."""
    return int((x + 50 - 40) // 80)


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
        "roof": "Place a Flower Pot before another plant. Use lobbers across the slope.",
        "boss": "Use Flower Pots and lobbers. Save Ice-shrooms for fireballs and Jalapenos for iceballs. Attack the lowered head.",
    }
    lines.append(f"Terrain: {terrain}. " + rules.get(terrain, ""))
    if state.get("conveyor"):
        lines.append("Conveyor cards are free and single-use. Use cards to leave room for new arrivals.")
    if special == "bowling":
        lines.append("Wall-nut Bowling: roll nuts into threatened lanes from columns 0 through 2 only.")
    elif special == "vases":
        lines.append("Vasebreaker: use break_vase to smash a vase, starting near the right edge. "
                     "Use its temporary seed packets before they expire. Open one at a time.")
    lines.append("")
    lines.append("Seed packets (slot: name, cost, status):")
    for s in state["seeds"]:
        status = "READY" if s["ready"] else "moving into view" if state.get("conveyor") else "recharging"
        afford = "" if s["cost"] is None or s["cost"] <= state["sun"] else " (can't afford)"
        lines.append(f"  {s['slot']}: {s['name']}, {s['cost']} sun, {status}{afford}")
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
- The game keeps running while you think (about 5 seconds), so zombies will have moved a little
  by the time your plan starts. Plan slightly ahead.
- Actions run strictly in your order. Each one happens as soon as you have enough sun and the seed
  has recharged, so you can queue things you can't afford yet ("save up" = put it next in the plan).
- Your new plan replaces any unfinished old one.
- You are asked again when the plan is used up, or when something important happens
  (a zombie shows up in a new place, you lose a plant, a lawn mower is used).
- An empty plan means: do nothing until something changes.

Rules of thumb:
- Sun is collected for you automatically. Sunflowers make more sun over time.
- A zombie that reaches the house in a row with no lawn mower loses the game. A mower clears its row once.
- Put Peashooters between the house and the zombies so they can hit. Prioritize threatened lanes
  with no mower before spending more sun on economy.
- Pumpkin can be planted over an existing plant to shield it.
- Upgrade plants go on top of their base plant: gatling_pea on repeater, twin_sunflower on sunflower,
  winter_melon on melon_pult, spikerock on spikeweed, cob_cannon on the left of two side-by-side kernel_pults.
- Each action is checked before it runs; invalid ones are rejected and you will see why next turn.

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
Pick for the terrain described in the request. Bring a Lily Pad for pool/fog and a Flower Pot and
lobbers for a roof. In night/fog, use mushrooms and an appropriate sun producer. During day,
mushrooms need Coffee Bean. Falling sun is collected for you automatically.
Upgrade plants (gatling_pea, gold_magnet, cob_cannon...)
can only be planted on top of their base plant, so they need that base plant in the loadout too.
Pick exactly the number of plants asked for, using
only names from the list. Answer with JSON only; keep "reasoning" to one or two short sentences
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


def pick_prompt(options, slots, zombies, forced=None, terrain="day"):
    lines = [f"Terrain: {terrain}. Choose exactly {slots} plants (list {slots} names)."]
    if forced:
        lines += [f"Crazy Dave has already locked these into your loadout (you will have them too): "
                  + ", ".join(forced)]
    lines += ["", "Available plants (name: sun cost):"]
    lines += [f"  {o['name']}: {o['cost']}" for o in options]
    if zombies:
        lines += ["", "Zombies previewed for this level: "
                  + ", ".join(f"{n} x{k}" for n, k in zombies.items())]
    return "\n".join(lines)


class ClaudeBrain:
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
        decision = self.ask(SYSTEM_PROMPT, board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        return self.ask(PICK_SYSTEM, pick_prompt(options, slots, zombies, forced, terrain), PICK_SCHEMA)


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


class ClaudeCodeBrain:
    """Sends each board to `claude -p` (headless Claude Code) and reads back JSON.
    Uses the account you logged in with (`claude auth login`), so it counts
    toward your subscription's usage limits instead of costing API money."""
    name = "subscription"

    def __init__(self, model=None, effort="medium", timeout=180):
        self.exe = find_claude_exe()
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.last_usage = None

    def decide(self, state, recent, queue=None):
        board = describe(state, recent, queue)
        decision = self.ask(SYSTEM_PROMPT, board, DECISION_SCHEMA)
        decision["_prompt"] = board
        return decision

    def pick_seeds(self, options, slots, zombies, forced=None, terrain="day"):
        return self.ask(PICK_SYSTEM, pick_prompt(options, slots, zombies, forced, terrain), PICK_SCHEMA)

    def ask(self, system, user, schema):
        import subprocess
        cmd = [self.exe, "-p",
               "--output-format", "json",
               "--json-schema", json.dumps(schema),
               "--system-prompt", system,
               "--tools", "",                 # no file/shell tools: it only answers
               "--setting-sources", "",       # ignore any CLAUDE.md / project settings
               "--no-session-persistence",
               "--effort", self.effort]
        if self.model:
            cmd += ["--model", self.model]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                              encoding="utf-8", timeout=self.timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300] or proc.stdout[:300]}")
        if data.get("is_error"):
            raise RuntimeError(str(data.get("result"))[:300])
        self.last_usage = data.get("usage")
        answer = data.get("structured_output")
        if answer is None:
            answer = json.loads(data.get("result") or "{}")
        return answer


# ---------------------------------------------------------------------------
# Simple rule-based player (no API needed)
# ---------------------------------------------------------------------------

ATTACKERS = ["gatling_pea", "repeater", "threepeater", "snow_pea", "peashooter", "split_pea",
             "cactus", "melon_pult", "kernel_pult", "cabbage_pult", "fume_shroom", "puff_shroom",
             "starfruit", "winter_melon"]
INSTANT = ["cherry_bomb", "jalapeno", "squash", "potato_mine"]
WALLS = ["tall_nut", "wall_nut"]


class SimpleBrain:
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
                               effort=os.environ.get("PVZ_EFFORT", "medium"))
    if name == "simple":
        return SimpleBrain()
    raise ValueError(f"unknown brain {name!r} (use 'subscription', 'claude' or 'simple')")
