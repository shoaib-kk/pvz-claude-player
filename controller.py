"""
Mouse controller for PvZ: plant, shovel, click.

All positions are in GAME pixels (the 800x600 game area) and get converted to
screen pixels using the window's position, so moving the window is fine.
Play in WINDOWED mode, not fullscreen.

Usage:
    python controller.py calibrate     # hovers (no clicks) over every seed slot,
                                       # the shovel and grid corners - check they line up
    python controller.py test          # plants seed slot 0 at row 2, col 0

Safety: slam the mouse into any screen corner to abort (pyautogui fail-safe).
"""

import ctypes
import sys
import time

import pyautogui
import win32con
import win32gui

import offsets as O

# Make screen coordinates match real pixels on scaled displays (125%, 150%...).
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    ctypes.windll.user32.SetProcessDPIAware()

WINDOW_TITLE = "Plants vs. Zombies"

# --- Layout in game pixels (adjust after running `calibrate`) --------------
GRID_LEFT = 40      # x where column 0 starts
GRID_TOP = 80       # y where row 0 starts
CELL_W = 80
CELL_H = 100        # Pool/Fog levels use 85 with 6 rows

# Fallbacks only: when the game is readable, seed/shovel positions come from memory.
SEED_X0 = 116       # x centre of seed slot 0 (measured, 8-slot bank)
SEED_DX = 54        # distance between slot centres
SEED_Y = 43

SHOVEL = (567, 38)  # measured with an 8-slot bank; moves with the bank width

CLICK_DELAY = 0.12  # pause between clicks so the game registers them
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02


class Controller:
    def __init__(self, move_duration=0.15):
        self.hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
        if not self.hwnd:
            sys.exit(f'Window "{WINDOW_TITLE}" not found. Is the game running (windowed)?')
        self.move_duration = move_duration  # >0 makes the cursor visibly glide (good on camera)
        try:
            from state import GameReader
            self.reader = GameReader()
        except Exception:  # noqa: BLE001 - fall back to the fixed layout
            self.reader = None

    def _bank(self):
        """(bank_ptr, bank_x, bank_y, bank_w) from memory, or None."""
        if not self.reader:
            return None
        try:
            board = self.reader.board()
            if not board:
                return None
            pm = self.reader.pm
            bank = pm.read_uint(board + O.SEED_BANK)
            return bank, *(pm.read_int(bank + o) for o in (O.OBJ_X, O.OBJ_Y, O.OBJ_W))
        except Exception:  # noqa: BLE001
            return None

    def focus(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:  # noqa: BLE001 - Windows sometimes refuses; clicking still focuses
            pass

    def to_screen(self, gx, gy):
        ox, oy = win32gui.ClientToScreen(self.hwnd, (0, 0))
        return ox + int(gx), oy + int(gy)

    # --- primitives ----------------------------------------------------------
    def hover(self, gx, gy):
        pyautogui.moveTo(*self.to_screen(gx, gy), duration=self.move_duration)

    def click(self, gx, gy, button="left"):
        if not (0 <= gx < 800 and 0 <= gy < 600):
            raise ValueError(f"click ({gx}, {gy}) is outside the game window")
        self.hover(gx, gy)
        pyautogui.click(button=button)
        time.sleep(CLICK_DELAY)

    @staticmethod
    def cell_center(row, col, terrain="day"):
        rows = 6 if terrain in ("pool", "fog") else 5
        if not (0 <= row < rows and 0 <= col < O.COLS):
            raise ValueError(f"cell ({row}, {col}) is off the {terrain} lawn")
        height = 85 if terrain in ("pool", "fog", "roof", "boss") else CELL_H
        slope = 20 * max(0, 5 - col) - 10 if terrain in ("roof", "boss") else 0
        return GRID_LEFT + col * CELL_W + CELL_W // 2, GRID_TOP + row * height + height // 2 + slope

    def seed_center(self, slot):
        info = self._bank()
        if info:
            bank, bx, by, _ = info
            card = bank + O.SB_FIRST_CARD + slot * O.CARD_SIZE
            pm = self.reader.pm
            x, y, w, h = (pm.read_int(card + o) for o in (O.OBJ_X, O.OBJ_Y, O.OBJ_W, O.OBJ_H))
            x += pm.read_int(card + O.C_OFFSET_X)
            return bx + x + w // 2, by + y + h // 2
        return SEED_X0 + slot * SEED_DX, SEED_Y

    def shovel_center(self):
        info = self._bank()
        if info:
            _, bx, _, bw = info
            return bx + bw + 35, 38
        return SHOVEL

    # --- actions the AI will use ---------------------------------------------
    def plant(self, slot, row, col, terrain="day", pickup=None):
        target = self.cell_center(row, col, terrain)
        seed = pickup if pickup is not None else self.seed_center(slot)
        if not (0 <= seed[0] < 800 and 0 <= seed[1] < 600):
            return
        self.click(*seed)
        self.click(*target)
        # Right-click cancels the held seed if planting failed (not enough sun etc.)
        pyautogui.click(button="right")

    def shovel(self, row, col, terrain="day"):
        target = self.cell_center(row, col, terrain)
        self.click(*self.shovel_center())
        self.click(*target)
        pyautogui.click(button="right")

    def collect_sun(self):
        """Click every uncollected sun on the lawn. Returns how much sun was clicked."""
        board = self.reader.board()
        total = 0
        for drop in self.reader.sun_drops(board):
            if 0 <= drop["x"] < 800 and 0 <= drop["y"] < 600:
                self.click(drop["x"], drop["y"])
                total += drop["value"]
        return total

    # --- pausing -------------------------------------------------------------
    # Space toggles pause (memory flag board+PAUSED) and shows the "Game Paused"
    # dialog; space again resumes and hides it. The same dialog also appears when
    # the window loses focus; wake() handles that case by clicking "Resume Game".
    # Clicks on the lawn are ignored while paused, so: pause -> think -> resume -> act.
    DIALOG_POINTS = [(260, 200), (540, 200), (260, 380), (540, 380)]

    def dialog_kind(self):
        """Recognize the saved-game and focus-loss overlays from their panel geometry."""
        x0, y0 = self.to_screen(0, 0)
        try:
            img = pyautogui.screenshot(region=(x0, y0, 800, 600))
        except OSError:  # screen locked / display asleep: can't look, assume no dialog
            return None
        continue_frame = (img.getpixel(p) for p in ((160, 260), (200, 360), (360, 360), (400, 405)))
        if all(50 <= g < 180 and abs(r - g) < 15 and b > g + 15 for r, g, b in continue_frame):
            return "continue"
        if all(g < 80 and b >= g for (_, g, b) in (img.getpixel(p) for p in self.DIALOG_POINTS)):
            return "pause"
        return None

    def dialog_up(self):
        return self.dialog_kind() == "pause"

    def wake(self):
        """Bring the game to the front and dismiss the focus-loss dialog if it's up."""
        self.focus()
        time.sleep(0.3)
        dialog = self.dialog_kind()
        if dialog == "continue":
            self.click(280, 371)
            time.sleep(0.3)
        elif dialog == "pause":
            self.click(395, 448)  # "Resume Game"
            time.sleep(0.3)

    def is_paused(self):
        return self.reader.paused(self.reader.board())

    def pause(self):
        if not self.is_paused():
            pyautogui.press("space")
            time.sleep(0.15)

    def resume(self):
        if self.is_paused():
            pyautogui.press("space")
            time.sleep(0.15)

    # --- calibration ---------------------------------------------------------
    def calibrate(self, slots=None):
        if slots is None:
            info = self._bank()
            slots = self.reader.pm.read_int(info[0] + O.SB_COUNT) if info else 6
        print("Hovering only, no clicks. Watch where the cursor lands.")
        print("Seed/shovel positions from:", "game memory" if self._bank() else "fixed layout")
        self.wake()
        self.focus()
        time.sleep(0.5)
        for s in range(slots):
            print(f"seed slot {s}")
            self.hover(*self.seed_center(s))
            time.sleep(0.8)
        print("shovel")
        self.hover(*self.shovel_center())
        time.sleep(0.8)
        for r, c in [(0, 0), (0, O.COLS - 1), (O.ROWS - 1, 0), (O.ROWS - 1, O.COLS - 1)]:
            print(f"cell row {r} col {c}")
            self.hover(*self.cell_center(r, c))
            time.sleep(0.8)
        print("Done. Adjust the layout numbers at the top of controller.py if anything is off.")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "calibrate"
    ctl = Controller()
    if cmd == "calibrate":
        ctl.calibrate()
    elif cmd == "test":
        ctl.focus()
        time.sleep(0.5)
        ctl.plant(slot=0, row=2, col=0)
        print("Planted slot 0 at row 2, col 0 (if you had the sun).")
    else:
        sys.exit("usage: python controller.py [calibrate|test]")


if __name__ == "__main__":
    main()
