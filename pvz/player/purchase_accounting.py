"""Confirmed packet spending and observed plant provenance, without loss-cause guesses."""
from collections import Counter
from pvz.player.sun_accounting import known_cost, verified_costs
from pvz.player.placement import UPGRADES

CONSUMABLES = {"cherry_bomb", "jalapeno", "squash", "ice_shroom", "doom_shroom", "grave_buster",
               "coffee_bean", "blover", "tangle_kelp", "hypno_shroom", "explode_o_nut", "potato_mine"}


def key(plant):
    return plant["row"], plant["col"], plant.get("type", plant.get("seed"))


class PurchaseLedger:
    def __init__(self):
        self.initialized = False
        self.initial = Counter()
        self.initial_mowers = None
        self.active = {}
        self.purchases = Counter()
        self.spending = Counter()
        self.unknown_purchases = Counter()
        self.missing = {origin: Counter() for origin in ("initial", "purchased", "unattributed")}
        self.purchased_missing_spend = 0
        self.unknown_missing_cost = 0
        self.removed = Counter()
        self.costs = {}

    def observe(self, state):
        if not state.get("in_level") or "plants" not in state:
            return
        self.costs.update(verified_costs(state))
        present = {key(p) for p in state["plants"]}
        if not self.initialized:
            self.initialized = True
            self.initial.update(p["type"] for p in state["plants"])
            self.initial_mowers = list(state.get("mowers", []))
            self.active = {k: ("initial", 0) for k in present}
            return
        for k in self.active.keys() - present:
            origin, paid = self.active[k]
            # One-use disappearances do not establish destruction or lost investment.
            if k[2] not in CONSUMABLES:
                self.missing[origin][k[2]] += 1
                if origin == "purchased":
                    if paid is None:
                        self.unknown_missing_cost += 1
                    else:
                        self.purchased_missing_spend += paid
        self.active = {k: self.active.get(k, ("unattributed", None)) for k in present}

    def purchased(self, action, packet, before):
        self.observe(before)
        name = packet["name"]
        cost = packet.get("cost")
        self.purchases[name] += 1
        if known_cost(cost):
            self.spending[name] += cost
        else:
            self.unknown_purchases[name] += 1
        if name in UPGRADES:
            self._remove((action["row"], action["col"], UPGRADES[name]))
            if name == "cob_cannon":
                self._remove((action["row"], action["col"] + 1, "kernel_pult"))
        self.active[(action["row"], action["col"], name)] = ("purchased", cost)

    def _remove(self, k):
        old = self.active.pop(k, None)
        if old:
            self.removed[k[2]] += 1

    def shoveled(self, action, before, after=None):
        self.observe(before)
        row, col = action["row"], action["col"]
        if after is not None:
            remaining = {key(p) for p in after["plants"]}
            for p in before["plants"]:
                if (p["row"], p["col"]) == (row, col) and key(p) not in remaining:
                    self._remove(key(p))
            return
        target = before["grid"][row][col] or next(
            (p["type"] for p in before["plants"] if (p["row"], p["col"]) == (row, col)), None)
        self._remove((row, col, target))

    def metrics(self):
        counts = sum((c for c in self.missing.values()), Counter())
        replacement = (None if any(not known_cost(self.costs.get(n)) for n in counts)
                       else sum(self.costs[n] * c for n, c in counts.items()))
        return {"initial_plants": dict(self.initial), "initial_mowers": self.initial_mowers,
                "purchases": dict(self.purchases), "packet_sun_spent": sum(self.spending.values()),
                "spending_by_seed": dict(self.spending), "unknown_cost_purchases": dict(self.unknown_purchases),
                "disappeared_by_origin": {o: dict(c) for o, c in self.missing.items()},
                "replacement_value_disappeared": replacement,
                "purchased_disappeared_spend": self.purchased_missing_spend,
                "unknown_cost_disappeared": self.unknown_missing_cost,
                "intentional_removals_or_upgrades": dict(self.removed)}

    def report(self):
        m = self.metrics()
        lines = ["Purchase accounting (confirmed packet uses; disappearance cause and contribution unverified):",
                 f"  Initial plants supplied at takeover, no purchase charged: {dict(self.initial)}.",
                 f"  Actual packet sun spent: {m['packet_sun_spent']}; by seed: {dict(self.spending)}; "
                 f"unknown-cost purchases: {dict(self.unknown_purchases)}.",
                 f"  Non-consumable plants later disappeared, by origin: {m['disappeared_by_origin']}.",
                 f"  Replacement value of disappeared plants: {m['replacement_value_disappeared']} "
                 "(catalog value, NOT cash spent).",
                 f"  Original purchase spending on purchased plants later missing: "
                 f"{m['purchased_disappeared_spend']}; unknown-cost disappearances: {m['unknown_cost_disappeared']}.",
                 "  Free initial plants have zero purchase spending. Missing plants may have bought time or "
                 "dealt damage. Intentional shovel/upgrade removals are separate.",
                 "  Provenance follows observed cell/type lifetimes and confirmed actions; unseen replacements "
                 "or plants appearing between observations are not assigned a purchase cost."]
        return "\n".join(lines)
