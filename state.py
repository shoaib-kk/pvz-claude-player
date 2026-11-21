"""
Reads the live PvZ game state from memory and returns it as a dict / JSON.

Usage:
    python state.py          # print state every 0.5s (Ctrl+C to stop)
    python state.py --once   # print one snapshot

Start a level first. If attaching fails, run your terminal as Administrator.
"""

import json
import struct
import sys
import time

import pymem

import offsets as O

# Steam's PlantsVsZombies.exe is only a launcher; the real game runs as popcapgame1.exe.
PROCESS_NAMES = ["popcapgame1.exe", "PlantsVsZombies.exe"]

PLANT_NAMES = [
    "peashooter", "sunflower", "cherry_bomb", "wall_nut", "potato_mine", "snow_pea",
    "chomper", "repeater", "puff_shroom", "sun_shroom", "fume_shroom", "grave_buster",
    "hypno_shroom", "scaredy_shroom", "ice_shroom", "doom_shroom", "lily_pad", "squash",
    "threepeater", "tangle_kelp", "jalapeno", "spikeweed", "torchwood", "tall_nut",
    "sea_shroom", "plantern", "cactus", "blover", "split_pea", "starfruit", "pumpkin",
    "magnet_shroom", "cabbage_pult", "flower_pot", "kernel_pult", "coffee_bean", "garlic",
    "umbrella_leaf", "marigold", "melon_pult", "gatling_pea", "twin_sunflower",
    "gloom_shroom", "cattail", "winter_melon", "gold_magnet", "spikerock", "cob_cannon",
    "imitater", "explode_o_nut", "giant_wall_nut", "sprout", "leftpeater",
]

PLANT_COSTS = [
    100, 50, 150, 50, 25, 175, 150, 200, 0, 25, 75, 75, 75, 25, 75, 125, 25, 50, 325, 25,
    125, 100, 175, 125, 0, 25, 125, 100, 125, 125, 125, 100, 100, 25, 100, 75, 50, 100,
    50, 300, 250, 150, 150, 225, 200, 50, 125, 500, 0,
]

ZOMBIE_NAMES = [
    "zombie", "flag", "conehead", "pole_vaulting", "buckethead", "newspaper",
    "screen_door", "football", "dancing", "backup_dancer", "ducky_tube", "snorkel",
    "zomboni", "bobsled", "dolphin_rider", "jack_in_the_box", "balloon", "digger",
    "pogo", "yeti", "bungee", "ladder", "catapult", "gargantuar", "imp", "dr_zomboss",
]


def name(table, idx):
    return table[idx] if 0 <= idx < len(table) else f"unknown_{idx}"


class GameReader:
    def __init__(self):
        self.pm = None
        for proc in PROCESS_NAMES:
            try:
                self.pm = pymem.Pymem(proc)
                break
            except pymem.exception.ProcessNotFound:
                continue
        if self.pm is None:
            raise pymem.exception.ProcessNotFound(PROCESS_NAMES[0])
        self.version = self._detect_profile()
        O.use(self.version)

    def _detect_profile(self):
        """Pick the offset profile whose root pointer actually reads.
        (The Steam launcher deletes the real exe after starting it, so we
        can't just read the file's version number.)"""
        for version, prof in O.PROFILES.items():
            try:
                root = self.pm.read_uint(prof["BASE"])
                if root:
                    self.pm.read_uint(root + prof["BOARD"])
                    return version
            except Exception:  # noqa: BLE001
                continue
        raise KeyError("None of the offset profiles in offsets.py match this game build.")

    # --- low-level helpers ---------------------------------------------------
    def _int(self, addr):
        return self.pm.read_int(addr)

    def _ptr(self, addr):
        return self.pm.read_uint(addr)  # PvZ is 32-bit, pointers are 4 bytes

    def _block(self, addr, size):
        return self.pm.read_bytes(addr, size)

    def board(self):
        """Pointer to the current level, or 0 if not in a level."""
        return self._ptr(self._ptr(O.BASE) + O.BOARD)

    def scene(self):
        """Which screen the game is on: 'intro' (Dave / plant chooser), 'playing',
        'zombies_won', 'award', 'menu'..."""
        value = self._int(self._ptr(O.BASE) + O.GAME_SCENE)
        return O.SCENES.get(value, f"unknown_{value}")

    def dave_talking(self):
        if O.DAVE_TALKING is None:
            return False
        return self._int(self._ptr(O.BASE) + O.DAVE_TALKING) != 0

    def mode(self):
        return self._int(self._ptr(O.BASE) + O.GAME_SCENE - 4)

    def tutorial(self, board):
        return self._int(board + O.SUN + 0x24)

    def chooser_layout(self):
        """Infer six/seven-row chooser geometry from several unselected cards."""
        chooser = self._ptr(self._ptr(O.BASE) + O.BOARD + 0x0C)
        if not chooser:
            return None
        # The GOTY Widget base adds fields ahead of the ChosenSeed array.
        for first in (0xA4, 0xBC):
            for top, step in ((123, 70), (128, 73)):
                matches = 0
                for index in range(48):
                    card = chooser + first + index * 0x3C
                    x, y, seed_type = (self._int(card + offset) for offset in (0, 4, 0x20))
                    if (x, y, seed_type) == (22 + 53 * (index % 8), top + step * (index // 8), index):
                        matches += 1
                if matches >= 4:
                    return top + 35, step
        return None

    def plant_points(self, board):
        """Plant hit locations, including the Zen Garden's separate layout."""
        points = []
        for raw, b in self._live_entries(board, O.PLANT_ARRAY, O.PLANT_MAX, O.PLANT_SIZE):
            if raw[b + O.P_DEAD]:
                continue
            x, y, width, height = (struct.unpack_from("<i", raw, b + o)[0]
                                  for o in (O.OBJ_X, O.OBJ_Y, O.OBJ_W, O.OBJ_H))
            if 0 <= x < 800 and 0 <= y < 600 and 0 < width <= 200 and 0 < height <= 200:
                points.append((x + width // 2, y + height // 2))
        return points

    def level_info(self, board):
        # The background and Adventure level fields precede the sun counter
        # in both offset profiles.
        background = self._int(board + O.SUN - 20)
        level = self._int(board + O.SUN - 16)
        terrain = O.BACKGROUNDS[background] if 0 <= background < len(O.BACKGROUNDS) else "unknown"
        adventure = self.mode() == 0 and 1 <= level <= 50
        return {
            "level": level if adventure else None,
            "terrain": terrain,
            "rows": 6 if terrain in ("pool", "fog") else 5,
            "conveyor": adventure and level in O.ADVENTURE_CONVEYORS,
            "special": O.ADVENTURE_SPECIALS.get(level) if adventure else None,
        }

    # --- sections ------------------------------------------------------------
    def sun(self, board):
        return self._int(board + O.SUN)

    def _live_entries(self, board, arr_off, max_off, size):
        """Yield (raw_bytes, offset) for each in-use entry of a game data array.
        The last 4 bytes of each entry are its ID; free slots have a 0 high word."""
        arr = self._ptr(board + arr_off)
        used = self._int(board + max_off)   # highest slot ever used this level
        if used == 0:
            return
        if used < 0 or used > 4096:
            raise ValueError(f"implausible array size {used}")
        raw = self._block(arr, used * size)
        for i in range(used):
            b = i * size
            if struct.unpack_from("<I", raw, b + size - 4)[0] >> 16:
                yield raw, b

    def plants(self, board):
        out = []
        for raw, b in self._live_entries(board, O.PLANT_ARRAY, O.PLANT_MAX, O.PLANT_SIZE):
            if raw[b + O.P_DEAD]:
                continue
            ptype = struct.unpack_from("<i", raw, b + O.P_TYPE)[0]
            row = struct.unpack_from("<i", raw, b + O.P_ROW)[0]
            col = struct.unpack_from("<i", raw, b + O.P_COL)[0]
            hp = struct.unpack_from("<i", raw, b + O.P_HP)[0]
            if not (0 <= row < 6 and 0 <= col < 9):
                continue  # unused slot with junk data
            plant = {"type": name(PLANT_NAMES, ptype), "row": row, "col": col, "hp": hp}
            if raw[b + O.P_ASLEEP]:
                plant["asleep"] = True
            out.append(plant)
        return out

    def zombies(self, board):
        out = []
        for raw, b in self._live_entries(board, O.ZOMBIE_ARRAY, O.ZOMBIE_MAX, O.ZOMBIE_SIZE):
            if raw[b + O.Z_DEAD]:
                continue
            ztype = struct.unpack_from("<i", raw, b + O.Z_TYPE)[0]
            row = struct.unpack_from("<i", raw, b + O.Z_ROW)[0]
            x = struct.unpack_from("<f", raw, b + O.Z_X)[0]
            hp = struct.unpack_from("<i", raw, b + O.Z_HP)[0]
            armor = struct.unpack_from("<i", raw, b + O.Z_ARMOR_HP)[0]
            if not (0 <= row < 6) or hp <= 0 or x != x:  # x != x catches NaN
                continue
            zombie = {
                "type": name(ZOMBIE_NAMES, ztype), "row": row, "x": round(x),
                "hp": hp, "armor_hp": armor,
            }
            if zombie["type"] == "dr_zomboss":
                phase = struct.unpack_from("<i", raw, b + O.Z_PHASE)[0]
                zombie["phase"] = "head lowered" if 86 <= phase <= 90 else "head raised"
                projectile = struct.unpack_from("<I", raw, b + O.Z_BOSS_PROJECTILE)[0]
                lane = struct.unpack_from("<i", raw, b + O.FIREBALL_ROW)[0]
                if projectile and 0 <= lane < 5:
                    fire = raw[b + O.FIREBALL_ROW + 4]
                    zombie["projectile"] = {"type": "fire" if fire else "ice", "row": lane, "id": projectile}
            out.append(zombie)
        out.sort(key=lambda z: z["x"])  # closest to the house first
        return out

    def coins(self, board):
        """Every uncollected pickup on the lawn (sun, money, level rewards)."""
        arr = self._ptr(board + O.COIN_ARRAY)
        used = self._int(board + O.COIN_MAX)
        if used <= 0:
            return []
        raw = self._block(arr, min(used, 1024) * O.COIN_SIZE)
        out = []
        for i in range(min(used, 1024)):
            b = i * O.COIN_SIZE
            ctype = struct.unpack_from("<i", raw, b + O.CO_TYPE)[0]
            if raw[b + O.CO_DEAD] or raw[b + O.CO_COLLECTED] or not (0 < ctype < 40):
                continue
            x = struct.unpack_from("<f", raw, b + O.CO_X)[0]
            y = struct.unpack_from("<f", raw, b + O.CO_Y)[0]
            if x != x or y != y:
                continue
            coin = {"x": round(x) + 30, "y": round(y) + 30, "type": ctype}
            if ctype == O.USABLE_SEED_PACKET:
                coin["x"] = round(x) + 20
                coin["name"] = name(PLANT_NAMES, struct.unpack_from("<i", raw, b + O.CO_SEED)[0])
                coin["packet_id"] = f"{i}:{struct.unpack_from('<I', raw, b + O.COIN_SIZE - 4)[0]}"
                age = struct.unpack_from("<i", raw, b + O.CO_AGE)[0]
                elapsed = struct.unpack_from("<i", raw, b + O.CO_DISAPPEAR)[0]
                fading = struct.unpack_from("<i", raw, b + O.CO_FADE)[0] > 0
                coin["age_seconds"] = round(max(0, age) / 100, 1)
                coin["expires_in"] = round(max(0, O.VASE_PACKET_LIFETIME - elapsed) / 100, 1)
                coin["flashing"] = elapsed > O.VASE_PACKET_LIFETIME - 300
                coin["fading"] = fading
            out.append(coin)
        return out

    def sun_drops(self, board):
        """Uncollected sun on the lawn, with the game-pixel point to click."""
        return [{"x": c["x"], "y": c["y"], "value": O.SUN_TYPES[c["type"]]}
                for c in self.coins(board) if c["type"] in O.SUN_TYPES]

    def vase_seeds(self, board):
        """Vasebreaker has lawn packets rather than a normal seed bank."""
        return [
            {"name": coin["name"], "slot": None, "cost": 0, "ready": True,
             "pickup": (coin["x"], coin["y"]),
             **{key: coin[key] for key in ("packet_id", "age_seconds", "expires_in", "flashing", "fading")}}
            for coin in self.coins(board) if coin["type"] == O.USABLE_SEED_PACKET
        ]

    def awards(self, board):
        """End-of-level rewards (trophy, money bag, note, new seed packet...)."""
        return [c for c in self.coins(board) if c["type"] in O.AWARD_TYPES]

    def mowers(self, board, num_rows=O.ROWS):
        """List of 5 (or 6) booleans: True if that row still has its mower."""
        arr = self._ptr(board + O.MOWER_ARRAY)
        used = self._int(board + O.MOWER_MAX)
        rows = [False] * num_rows
        for i in range(max(0, min(used, 32))):
            e = arr + i * O.MOWER_SIZE
            row = self._int(e + O.M_ROW)
            if 0 <= row < num_rows and not self.pm.read_uchar(e + O.M_DEAD):
                rows[row] = True
        return rows

    def cell_types(self, board, num_rows=O.ROWS):
        """cell_types[row][col]: 1 grass, 2 bare dirt, 3 pool, 4 high ground."""
        flat = struct.unpack("<54i", self._block(board + O.GRID_TYPES, 54 * 4))
        return [[flat[c * 6 + r] for c in range(O.COLS)] for r in range(num_rows)]

    def grid_items(self, board):
        items = []
        for raw, b in self._live_entries(board, O.GRID_ITEM_ARRAY, O.GRID_ITEM_MAX, O.GRID_ITEM_SIZE):
            kind = O.GRID_ITEMS.get(struct.unpack_from("<i", raw, b + O.GI_TYPE)[0])
            if kind is None or raw[b + O.GI_DEAD]:
                continue
            col, row = struct.unpack_from("<2i", raw, b + O.GI_COL)
            if 0 <= row < 6 and 0 <= col < O.COLS:
                item = {"type": kind, "row": row, "col": col}
                if kind == "vase":
                    # Read only the visible sprite. Plain vases never reveal their contents.
                    appearance = struct.unpack_from("<i", raw, b + O.GI_STATE)[0]
                    item["appearance"] = O.VASE_APPEARANCES.get(appearance, "unknown")
                items.append(item)
        ice_start = struct.unpack("<6i", self._block(board + O.GRID_TYPES + 0x4A4, 24))
        ice_timers = struct.unpack("<6i", self._block(board + O.GRID_TYPES + 0x4BC, 24))
        for row, (left, timer) in enumerate(zip(ice_start, ice_timers)):
            if timer > 0 and left <= 750:
                first_col = max(0, min(8, (left + 12 - 40) // 80))
                items.extend({"type": "ice", "row": row, "col": col} for col in range(first_col, 9))
        return items

    def paused(self, board):
        return bool(self.pm.read_uchar(board + O.PAUSED))

    def wave(self, board):
        return [self._int(board + O.WAVE_NOW), self._int(board + O.WAVE_TOTAL)]

    def seeds(self, board, conveyor=False):
        bank = self._ptr(board + O.SEED_BANK)
        count = self._int(bank + O.SB_COUNT)
        if not (0 < count <= 10):
            raise ValueError(f"implausible seed slot count {count}")
        out = []
        for i in range(count):
            c = bank + O.SB_FIRST_CARD + i * O.CARD_SIZE
            ptype = self._int(c + O.C_TYPE)
            if ptype == -1:
                continue
            ready = bool(self.pm.read_bool(c + O.C_USABLE))
            if conveyor:
                # The rightmost moving cards cannot be clicked until inside the window.
                x = self._int(bank + O.OBJ_X) + self._int(c + O.OBJ_X) + self._int(c + O.C_OFFSET_X)
                ready = ready and x + self._int(c + O.OBJ_W) <= 800
            out.append({
                "slot": i,
                "name": name(PLANT_NAMES, ptype),
                "cost": 0 if conveyor else PLANT_COSTS[ptype] if 0 <= ptype < len(PLANT_COSTS) else None,
                "ready": ready,
                "recharge": [self._int(c + O.C_RECHARGE_NOW), self._int(c + O.C_RECHARGE_MAX)],
            })
        return out

    # --- full snapshot -------------------------------------------------------
    def snapshot(self):
        board = self.board()
        if not board:
            return {"version": self.version, "in_level": False}

        state = {"version": self.version, "in_level": True, **self.level_info(board)}
        rows = state["rows"]
        errors = {}
        # Each section is read separately so one bad offset doesn't hide the rest.
        for key, fn in [("sun", self.sun), ("wave", self.wave), ("paused", self.paused),
                        ("tutorial", self.tutorial),
                        ("seeds", lambda b: self.vase_seeds(b) if state["special"] == "vases"
                         else self.seeds(b, state["conveyor"])),
                        ("plants", self.plants),
                        ("zombies", self.zombies), ("mowers", lambda b: self.mowers(b, rows)),
                        ("sun_drops", self.sun_drops), ("awards", self.awards),
                        ("cells", lambda b: self.cell_types(b, rows)), ("items", self.grid_items)]:
            try:
                state[key] = fn(board)
            except Exception as e:  # noqa: BLE001 - we want to report any failure
                errors[key] = f"{type(e).__name__}: {e}"
        if "plants" in state:
            grid = [[None] * O.COLS for _ in range(rows)]
            for p in state["plants"]:
                if p["row"] < rows and p["type"] not in ("pumpkin", "lily_pad", "flower_pot", "coffee_bean"):
                    grid[p["row"]][p["col"]] = p["type"]
            state["grid"] = grid
        if errors:
            state["errors"] = errors  # tells you which offsets to fix
        return state


def main():
    try:
        reader = GameReader()
    except pymem.exception.ProcessNotFound:
        sys.exit("Plants vs. Zombies is not running. Start the game first.")
    except pymem.exception.CouldNotOpenProcess:
        sys.exit("Could not open the game process. Run this terminal as Administrator.")
    except KeyError as e:
        sys.exit(str(e))

    if "--once" in sys.argv:
        print(json.dumps(reader.snapshot(), indent=2))
        return

    try:
        while True:
            snap = reader.snapshot()
            print("\033[2J\033[H" + json.dumps(snap, indent=2))  # clear screen, redraw
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
