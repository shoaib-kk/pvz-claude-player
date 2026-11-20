"""Read-only packet arithmetic and evidence rules; no plant or position selection."""


MECHANICS_AND_EVIDENCE = """

Mechanics and evidence take precedence over your journal and your earlier plans:
- Current packet costs, board readings, and stated game mechanics are facts. Journal strategies
  are revisable hypotheses. Check claims against those facts before applying or repeating them.
- Sun after a packet purchase = current sun minus that packet's cost. A 0-sun packet spends
  exactly 0 sun and cannot increase another purchase's sun shortfall through sun spending.
- Separate sun spending from other tradeoffs: a lawn cell, packet recharge, a loadout slot,
  and any separately purchased support. Packet cost alone is not a full placement cost.
- If a claim that a plant wastes or saves sun contradicts its actual cost, reject that cost
  argument. Assess other tradeoffs separately; zero sun cost does not guarantee a useful placement.
- A plant disappearing or being eaten does not establish that it dealt no damage or bought no
  time. Use measured evidence when available; otherwise those contributions are unknown.
"""


def known_cost(value):
    return type(value) is int and value >= 0


def packet_options(seeds):
    """One row per packet kind, preferring a ready copy on conveyors."""
    result = {}
    for seed in seeds:
        name = seed.get("name", "")
        if name.startswith("unknown") or not name:
            continue
        if name not in result or seed.get("ready") and not result[name].get("ready"):
            result[name] = seed
    return list(result.values())


def sun_accounting(state, queue=()):
    """Counterfactual balances, holding income and all non-sun constraints separate.

    A packet kind is not a selected move: these calculations assert neither that it
    has a legal target nor that the executor will let it bypass earlier actions.
    """
    sun = state["sun"]
    packets = packet_options(state.get("seeds", []))
    costs = {s["name"]: s.get("cost") for s in packets}
    reference = next((a for a in queue or [] if a.get("type") == "plant"
                      and known_cost(costs.get(a.get("seed"))) and costs[a["seed"]] > 0), None)
    reference_cost = costs[reference["seed"]] if reference else None
    before_gap = max(0, reference_cost - sun) if reference else None
    rows = []
    for packet in packets:
        cost = packet.get("cost")
        if not packet.get("ready") or not known_cost(cost):
            continue
        affordable = cost <= sun
        after = sun - cost if affordable else None
        compare = reference and packet["name"] != reference["seed"] and affordable
        gap = max(0, reference_cost - after) if compare else None
        rows.append({"seed": packet["name"], "cost": cost, "affordable": affordable,
                     "sun_after": after, "reference_shortfall": gap,
                     "extra_shortfall": gap - before_gap if compare else None})
    return {"sun": sun, "reference": reference["seed"] if reference else None,
            "reference_cost": reference_cost, "wait_shortfall": before_gap, "packets": rows}


def accounting_lines(state, queue=()):
    accounting = sun_accounting(state, queue)
    sun = accounting["sun"]
    lines = ["", "Sun-only comparison (packet costs; no future income assumed; legality, recharge, "
             "supports, group costs and queue order are separate):"]
    reference = accounting["reference"]
    if reference:
        lines.append(f"  Reference: queued {reference} packet, {accounting['reference_cost']} sun. "
                     f"Wait: sun stays {sun}; shortfall {accounting['wait_shortfall']}.")
    for row in accounting["packets"]:
        if not row["affordable"]:
            lines.append(f"  {row['seed']}: cost {row['cost']}; cannot afford, shortfall {row['cost'] - sun}.")
            continue
        text = f"  {row['seed']}: {sun}-{row['cost']}={row['sun_after']} sun"
        if row["reference_shortfall"] is not None:
            text += f"; {reference} shortfall {row['reference_shortfall']} (extra {row['extra_shortfall']})"
        lines.append(text + ".")
    if state.get("terrain") in ("night", "fog") and not state.get("conveyor") and not state.get("special"):
        producers = sum(p["type"] in ("sunflower", "sun_shroom", "twin_sunflower")
                        and not p.get("asleep") for p in state.get("plants", []))
        lines.append(f"  Observed awake sun producers: {producers}; "
                     f"sun drops: {len(state.get('sun_drops', []))}; no falling sun on this terrain.")
    return lines


def verified_costs(state=None, names=()):
    """Use the reader's catalog and any overriding observed packet costs, without attaching."""
    from state import PLANT_NAMES, PLANT_COSTS
    costs = dict(zip(PLANT_NAMES, PLANT_COSTS))
    if names:
        costs = {n: costs[n] for n in dict.fromkeys(names) if n in costs}
    for packet in (state or {}).get("seeds", []):
        costs[packet["name"]] = packet.get("cost")
    return costs
