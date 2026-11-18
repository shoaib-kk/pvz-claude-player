"""
The "Choose your plants!" screen: lets the brain pick the loadout and clicks it in.

Card status is read from the screen (the chooser grid is in plant-ID order):
  available  - bright card, can be picked
  chosen     - darkened, already in the seed bank
  unusable   - dimmed by the game for this level (e.g. mushrooms by day, pool plants without a pool)
  locked     - empty slot (not bought yet)
"""

import time

import pyautogui

from state import PLANT_COSTS, PLANT_NAMES

LETS_ROCK = (233, 565)
BANK_SLOT0 = (112, 42)


def card_pos(i):
    """Centre of chooser card i (plant id), in game pixels."""
    return 47 + 53 * (i % 8), 155 + 70 * (i // 8)


def screenshot(ctl):
    x0, y0 = ctl.to_screen(0, 0)
    return pyautogui.screenshot(region=(x0, y0, 800, 600))


def in_chooser(ctl, img=None):
    """True when the chooser panel (brown) is where the lawn normally is."""
    img = img or screenshot(ctl)
    pts = [img.getpixel(p) for p in ((12, 300), (452, 300), (230, 102))]
    brown = all(r > g > b and r - b > 40 and r < 200 for (r, g, b) in pts[:2])
    return brown


def card_status(img, i):
    x, y = card_pos(i)
    px = [img.getpixel((x + dx, y + dy)) for dx in (-18, 0, 18) for dy in (22, 26)]
    r, g, b = (sum(p[k] for p in px) // len(px) for k in range(3))
    total = r + g + b
    if r > g + 25 and r > b + 40 and total < 250:
        return "locked"
    if total < 160:
        return "chosen"
    if total < 330:
        return "unusable"
    return "available"


def read_chooser(ctl):
    img = screenshot(ctl)
    return {PLANT_NAMES[i]: card_status(img, i) for i in range(48)}  # imitater skipped


def bank_size(ctl):
    from offsets import SB_COUNT, SEED_BANK
    r = ctl.reader
    try:
        board = r.board()
        return r.pm.read_int(r.pm.read_uint(board + SEED_BANK) + SB_COUNT)
    except Exception:  # noqa: BLE001
        return 6


def bank_filled(ctl, slots=10):
    """How many seed-bank slots hold a card, read from the screen.
    (The bank's memory isn't filled in until the level starts.)
    A card's face is light; an empty slot is dark brown."""
    img = screenshot(ctl)
    count = 0
    for i in range(slots):
        x = BANK_SLOT0[0] + 54 * i
        if x > 520:
            break
        # The cost strip at the bottom of a card is light (or grey when dimmed);
        # an empty slot / the shovel box is dark.
        px = [img.getpixel((x + dx, 66)) for dx in (-12, 0, 12)]
        if sum(sum(p) for p in px) / len(px) > 250:
            count += 1
        else:
            break  # cards fill from the left, so the first empty slot ends the run
    return count


def clear_bank(ctl, log=print):
    """Remove the cards left from last time. Cards Crazy Dave locked in can't be
    removed, so stop once clicking no longer changes anything. Returns cards left."""
    filled = bank_filled(ctl)
    while filled > 0:
        # Locked cards stay in front; click the first card after them.
        for i in range(filled):
            ctl.click(BANK_SLOT0[0] + 54 * i, BANK_SLOT0[1])
            time.sleep(0.8)  # card flies back
            now = bank_filled(ctl)
            if now < filled:
                filled = now
                break
        else:
            break  # nothing came out: everything left is locked
    if filled:
        log(f"    ({filled} plant(s) were locked in by Crazy Dave)")
    return filled


def preview_zombies(ctl):
    """Zombie types shown on the street during the chooser."""
    try:
        r = ctl.reader
        types = [z["type"] for z in r.zombies(r.board())]
    except Exception:  # noqa: BLE001
        types = []
    counts = {}
    for t in types:
        counts[t] = counts.get(t, 0) + 1
    return counts


def choose(ctl, brain, log=print):
    """Full chooser flow. Returns (picked_names, reasoning)."""
    ctl.wake()
    time.sleep(1.0)  # let the panel finish sliding in
    slots = bank_size(ctl)
    locked = clear_bank(ctl, log)
    status = read_chooser(ctl)
    forced = [n for n, s in status.items() if s == "chosen"]
    free = slots - locked
    options = [{"name": n, "cost": PLANT_COSTS[PLANT_NAMES.index(n)]}
               for n, s in status.items() if s == "available"]
    zombies = preview_zombies(ctl)
    pick = brain.pick_seeds(options, free, zombies, forced)
    names = [n for n in pick.get("seeds", []) if any(o["name"] == n for o in options)]
    names = list(dict.fromkeys(names))[:free]  # de-duplicate, cap
    if len(names) < free:  # top up so "Let's Rock" is allowed
        for o in options:
            if len(names) >= free:
                break
            if o["name"] not in names:
                names.append(o["name"])
        log(f"    (topped up the loadout to {free} plants)")
    for n in names:
        ctl.click(*card_pos(PLANT_NAMES.index(n)))
        time.sleep(0.5)
    filled = bank_filled(ctl)
    if filled < locked + len(names):
        log(f"    (only {filled - locked} of {len(names)} picks landed in the bank)")
    time.sleep(0.6)
    ctl.click(*LETS_ROCK)
    return forced + names, pick.get("reasoning", "")
