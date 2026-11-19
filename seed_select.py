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


def card_pos(i, layout=(155, 70)):
    """Centre of chooser card i (plant id), in game pixels."""
    top, step = layout
    return 47 + 53 * (i % 8), top + step * (i // 8)


def screenshot(ctl):
    x0, y0 = ctl.to_screen(0, 0)
    return pyautogui.screenshot(region=(x0, y0, 800, 600))


def in_chooser(ctl, img=None):
    """True when the chooser panel (brown) is where the lawn normally is."""
    img = img or screenshot(ctl)
    pts = [img.getpixel(p) for p in ((12, 300), (452, 300), (230, 102))]
    brown = all(r > g > b and r - b > 40 and r < 200 for (r, g, b) in pts[:2])
    return brown


def card_status(img, i, layout=(155, 70)):
    x, y = card_pos(i, layout)
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


def read_chooser(ctl, layout=(155, 70)):
    img = screenshot(ctl)
    return {PLANT_NAMES[i]: card_status(img, i, layout) for i in range(48)}  # imitater skipped


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
        x, _ = ctl.seed_center(i)
        if x + 12 >= img.width:
            break
        # The cost strip at the bottom of a card is light (or grey when dimmed);
        # an empty slot / the shovel box is dark.
        px = [img.getpixel((x + dx, 66)) for dx in (-12, 0, 12)]
        if sum(sum(p) for p in px) / len(px) > 250:
            count += 1
        else:
            break  # cards fill from the left, so the first empty slot ends the run
    return count


def clear_bank(ctl, log=print, slots=10):
    """Remove the cards left from last time. Cards Crazy Dave locked in can't be
    removed, so stop once clicking no longer changes anything. Returns cards left."""
    filled = bank_filled(ctl, slots)
    while filled > 0:
        # Locked cards stay in front; click the first card after them.
        for i in range(filled):
            ctl.click(*ctl.seed_center(i))
            time.sleep(0.8)  # card flies back
            now = bank_filled(ctl, slots)
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
    locked = clear_bank(ctl, log, slots)
    try:
        layout = ctl.reader.chooser_layout() or (155, 70)
    except Exception:
        layout = (155, 70)
    status = read_chooser(ctl, layout)
    forced = [n for n, s in status.items() if s == "chosen"]
    free = slots - locked
    options = [{"name": n, "cost": PLANT_COSTS[PLANT_NAMES.index(n)]}
               for n, s in status.items() if s == "available"]
    zombies = preview_zombies(ctl)
    terrain = ctl.reader.level_info(ctl.reader.board())["terrain"]
    pick = brain.pick_seeds(options, free, zombies, forced, terrain) if free else {}
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
        ctl.click(*card_pos(PLANT_NAMES.index(n), layout))
        time.sleep(0.5)
    filled = bank_filled(ctl, slots)
    if filled < locked + len(names):
        log(f"    (only {filled - locked} of {len(names)} picks landed in the bank)")
    time.sleep(0.6)
    ctl.click(*LETS_ROCK)
    warned = confirm_warning(ctl, log)
    return forced + names, pick.get("reasoning", ""), warned


# Crazy Dave's shop (first shown after 3-4): yellow "NEXT LEVEL" sign at the bottom centre.
STORE_SIGN_POINTS = ((380, 530), (480, 530), (430, 580))
STORE_NEXT_LEVEL = (430, 553)


def store_screen(img):
    return all(r > 220 and g > 180 and b < 130 for (r, g, b) in (img.getpixel(p) for p in STORE_SIGN_POINTS))


# Crazy Dave's "Upgrade to N seed slots?" offer during an intro (paid in game coins).
# A normal player accepts it; the bot does too.
SLOT_OFFER_POINTS = ((330, 470), (700, 470), (515, 520))
SLOT_OFFER_YES = (423, 497)


def slot_offer(img):
    return all(70 < r < 125 and b - r >= 25 for (r, g, b) in (img.getpixel(p) for p in SLOT_OFFER_POINTS))


# The stone "Warning" dialog (e.g. "You haven't chosen any sun producing plants") that the
# game shows after Let's Rock. The player's loadout stands: we answer Yes and tell the
# player afterwards, through the journal timeline.
WARNING_POINTS = ((215, 420), (230, 380), (400, 190))
WARNING_YES = (305, 393)


def warning_dialog(img):
    return all(70 < r < 125 and b - r >= 25 for (r, g, b) in (img.getpixel(p) for p in WARNING_POINTS))


def confirm_warning(ctl, log=print, wait=1.5):
    time.sleep(wait)
    if not warning_dialog(screenshot(ctl)):
        return False
    log("    (the game warned about the loadout; keeping the player's choice)")
    ctl.click(*WARNING_YES)
    return True
