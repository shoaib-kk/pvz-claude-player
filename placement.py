"""Shared placement mechanics used by the executor and read-only observations."""
import offsets as O

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
    if type(row) is not int or type(col) is not int:
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
        if not isinstance(action.get("seed"), str):
            return "reject", "plant requires a packet name in seed", None
        name = action["seed"].strip().lower().replace(" ", "_").replace("-", "_")
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
            return "reject", (f"({row},{col}) is water: plant lily_pad at ({row},{col}) first, "
                              f"then {name} at ({row},{col}) once the pad is there"), None
        elif state.get("terrain") in ("roof", "boss") and "flower_pot" not in plants:
            return "reject", "plant a Flower Pot here first", None
        elif name in {"spikeweed", "spikerock", "potato_mine"} and plants.keys() & SUPPORTS:
            return "reject", f"{name} can't go on a Lily Pad or Flower Pot; it needs solid ground", None
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


def legal_targets(state):
    """Unranked legal single-step targets, with funding/recharge reported separately.

    validate() checks placement before readiness, so a 'later' result still has
    a legal target. A plant needing a support is absent until that support exists.
    No board state is mutated and no target or packet is selected for the player.
    """
    packets = {}
    for seed in state.get("seeds", []):
        name = seed.get("name", "")
        if not name or name.startswith("unknown"):
            continue
        if name not in packets or seed.get("ready"):
            packets[name] = seed
    result = []
    for name, seed in packets.items():
        rows = {}
        for row, cells in enumerate(state.get("grid", [])):
            cols = [col for col in range(len(cells)) if validate(
                {"type": "plant", "seed": name, "row": row, "col": col}, state)[0] != "reject"]
            if cols:
                rows[row] = cols
        cost = seed.get("cost")
        result.append({"seed": name, "ready": bool(seed.get("ready")),
                       "affordable": None if cost is None else cost <= state["sun"],
                       "cost": cost, "rows": rows})
    return result


def _ranges(cols):
    groups = []
    for col in cols:
        if groups and col == groups[-1][-1] + 1:
            groups[-1].append(col)
        else:
            groups.append([col])
    return ",".join(str(g[0]) if len(g) == 1 else f"{g[0]}-{g[-1]}" for g in groups)


def legal_target_lines(state):
    lines = ["", "Legal planting cells now (unranked; r=row, values=columns). "
             "Use sun/recharge in Seeds above; queue order still applies. No support/shovel "
             "steps assumed; this is placement, not firing reach or usefulness."]
    shared = {}
    for entry in legal_targets(state):
        mask = tuple((r, tuple(cols)) for r, cols in entry["rows"].items())
        shared.setdefault(mask, []).append(entry["seed"])
    for mask, names in shared.items():
        targets = "; ".join(f"r{r}:{_ranges(cols)}" for r, cols in mask) or "none"
        lines.append(f"  {', '.join(names)}: {targets}")
    return lines


