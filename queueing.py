"""Player-controlled queue edits and grouping, with no plant or target selection."""
import copy
from execution import action_key, clean_action


TERMINAL = {"completed", "rejected", "failed", "canceled", "unfinished"}
MAX_PENDING = 15


def edit_queue(queue, decision, tracker, number, live_state=None):
    mode = decision.get("edit", "replace")  # old rule-based players remain compatible
    if mode not in ("keep", "append", "cancel", "replace"):
        raise ValueError(f"unknown queue edit: {mode}")
    incoming = decision.get("actions", [])
    cancel = decision.get("cancel", [])
    if not isinstance(incoming, list) or len(incoming) > 5:
        raise ValueError("actions must be a list of at most five actions")
    if not isinstance(cancel, list) or any(type(i) is not int for i in cancel):
        raise ValueError("cancel must contain action IDs")
    if mode in ("keep", "cancel") and incoming:
        raise ValueError(f"{mode} does not take new actions")
    if mode != "cancel" and cancel:
        raise ValueError("use edit=cancel for cancel IDs")
    if mode == "append" and len(queue) + len(incoming) > MAX_PENDING:
        raise ValueError(f"queue limit is {MAX_PENDING}; no actions were changed")
    # Groups must be contiguous and have one scheduling policy. Never infer a group
    # from plant names or from two actions happening to share a target.
    closed, previous, policies = set(), None, {}
    for a in incoming:
        if not isinstance(a, dict) or a.get("type") not in ("plant", "shovel", "break_vase"):
            raise ValueError("unknown action")
        g = a.get("group", 0)
        if type(g) is not int or g < 0 or type(a.get("independent", False)) is not bool:
            raise ValueError("group must be a nonnegative integer; independent must be a boolean")
        if g != previous:
            if previous:
                closed.add(previous)
            if g and g in closed:
                raise ValueError("group members must be adjacent")
        if g and g in policies and policies[g] != a.get("independent", False):
            raise ValueError("group members must use the same independent value")
        policies[g], previous = a.get("independent", False), g
        if "id" in a:
            if type(a["id"]) is not int:
                raise ValueError("action IDs must be integers")
            r = tracker.actions.get(a["id"])
            if r is None or action_key(a) != action_key(r["action"]):
                raise ValueError("existing action IDs cannot change their move; cancel and issue a new action")
    if mode == "keep":
        tracker.event("queue_edit", edit=mode, decision=number)
        return list(queue)
    if mode == "cancel":
        # Canceling part of a player-defined group cancels that group, not a newly
        # guessed subset that could execute with missing dependencies.
        groups = {a.get("_group") for a in queue if a.get("id") in cancel and a.get("_group")}
        result = []
        for a in queue:
            if a.get("id") in cancel or a.get("_group") in groups:
                tracker.finish(a, "canceled", f"player canceled in decision {number}")
            else:
                result.append(a)
        tracker.event("queue_edit", edit=mode, decision=number, cancel=cancel)
        return result
    result = list(queue) if mode == "append" else []
    observed = set(decision.get("_queue_ids", []))
    for a in incoming:
        ident = a.get("id")
        candidate = next((old for old in queue if old.get("id") == ident), None) if ident else None
        if ident and candidate is None:
            tracker.event("stale_action_ignored", action_id=ident, decision=number)
            continue  # a completed/canceled ID never becomes a new action
        if not ident:
            candidate = next((old for old in queue if mode == "replace"
                              and action_key(old) == action_key(a)
                              and not any(item["id"] == old["id"] for item in result)), None)
            # Reconcile legacy/no-ID echoes only for actions that were pending in
            # the board the player saw and actually completed while it was thinking.
            completed = [r for i, r in tracker.actions.items() if i in observed
                         and r["status"] == "completed" and action_key(r["action"]) == action_key(a)]
            satisfied = live_state and a.get("type") == "plant" and any(
                p["type"] == a.get("seed") and (p["row"], p["col"]) == (a.get("row"), a.get("col"))
                for p in live_state.get("plants", []))
            if completed and satisfied:
                tracker.event("stale_action_ignored", action_id=completed[-1]["id"], decision=number)
                continue
        if candidate:
            item = {**clean_action(a), "id": candidate["id"]}
        else:
            item = tracker.issue(a, number)
        if a.get("group", 0):
            item["_group"] = f"{number}:{a['group']}"
        if not any(old.get("id") == item["id"] for old in result):
            result.append(item)
    retained = {a["id"] for a in result}
    if mode == "replace":
        for old in queue:
            if old["id"] not in retained:
                tracker.finish(old, "canceled", f"player replaced in decision {number}")
    tracker.event("queue_edit", edit=mode, decision=number, queued=[a["id"] for a in result])
    return result


def units(queue):
    result = []
    for a in queue:
        if a.get("_group") and result and result[-1][0].get("_group") == a["_group"]:
            result[-1].append(a)
        else:
            result.append([a])
    return result


def check_unit(unit, state, validate):
    """Dry-run exactly the requested steps against a copy; reserve their combined sun.

    This is a readiness check, not a transaction: the live game may still invalidate a
    later step, so the caller revalidates before each click and reports partial failure.
    """
    if len(unit) == 1:
        status, reason, _ = validate(unit[0], state)
        return status, reason
    simulated = copy.deepcopy(state)
    used_packets = set()
    for a in unit:
        status, reason, seed = validate(a, simulated)
        if status != "ok":
            if seed and seed.get("slot") in used_packets and not simulated.get("conveyor"):
                return "reject", "group repeats a seed packet that must recharge between uses"
            return status, reason
        r, c = a["row"], a["col"]
        if a["type"] == "plant":
            simulated["sun"] -= seed.get("cost") or 0
            seed["ready"] = False
            used_packets.add(seed.get("slot"))
            simulated["plants"].append({"type": seed["name"], "row": r, "col": c, "hp": 300})
            if seed["name"] not in ("lily_pad", "flower_pot", "pumpkin", "coffee_bean"):
                simulated["grid"][r][c] = seed["name"]
        elif a["type"] == "shovel":
            # Removing a top plant leaves its support; a subsequent live validation
            # catches the uncommon cases where the game's layering differs.
            target = simulated["grid"][r][c]
            if target is None:
                target = next(p["type"] for p in simulated["plants"] if (p["row"], p["col"]) == (r, c))
            simulated["plants"] = [p for p in simulated["plants"]
                                   if not ((p["row"], p["col"]) == (r, c) and p["type"] == target)]
            simulated["grid"][r][c] = None
        else:
            simulated["items"] = [p for p in simulated["items"]
                                  if not (p["type"] == "vase" and (p["row"], p["col"]) == (r, c))]
    return "ok", "ok"
