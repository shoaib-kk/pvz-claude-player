"""Observable Vasebreaker changes; no target selection or concealed contents."""


def context(state):
    if state.get("special") != "vases":
        return None
    positions = frozenset((i["row"], i["col"]) for i in state.get("items", []) if i["type"] == "vase")
    packets = frozenset(s["packet_id"] for s in state.get("seeds", []) if "packet_id" in s)
    expiring = frozenset(s["packet_id"] for s in state.get("seeds", [])
                         if "packet_id" in s and (s.get("flashing") or s.get("fading")))
    return positions, packets, expiring


class Observer:
    def __init__(self):
        self.previous = None
        self.stage = 1
        self.packets = {}

    def observe(self, state):
        current = context(state)
        if current is None:
            return []
        positions, packets, expiring = current
        messages = []
        if self.previous is not None:
            old_positions, old_packets, old_expiring = self.previous
            if positions - old_positions:
                self.stage += 1
                messages.append(f"new vase arrangement observed ({self.stage}); {len(positions)} vases on the lawn")
            else:
                for row, col in sorted(old_positions - positions):
                    messages.append(f"vase at row {row} col {col} broke; this can result from a click or an explosion")
            for ident in sorted(old_packets - packets):
                old = self.packets[ident]
                messages.append(f"free {old['name']} packet {ident} is no longer on the lawn "
                                "(cause not inferred; completed plantings are recorded separately)")
        else:
            old_packets, old_expiring = frozenset(), frozenset()
        by_id = {s["packet_id"]: dict(s) for s in state.get("seeds", []) if "packet_id" in s}
        for ident in sorted(packets - old_packets):
            seed = by_id[ident]
            messages.append(f"free {seed['name']} packet {ident} appeared at lawn pixel {seed.get('pickup')}")
        for ident in sorted(expiring - old_expiring):
            seed = by_id[ident]
            messages.append(f"free {seed['name']} packet {ident} is flashing or fading near expiry")
        state["vase_stage"] = self.stage  # count observed arrangements; never infer unseen stages
        self.previous, self.packets = current, by_id
        return messages
