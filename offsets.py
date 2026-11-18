"""
Memory offsets for Plants vs. Zombies GOTY (1.2.0.1073, English).

These are commonly cited community values, NOT verified against your copy.
Confirm each one in Cheat Engine before trusting it:
  - Attach CE to PlantsVsZombies.exe
  - Add address manually: pointer, base "PlantsVsZombies.exe"+0x2A9EC0 (= 0x6A9EC0),
    offsets 0x768 then 0x5560  -> should show your current sun.
If sun is right, BASE and BOARD are right, and the rest is likely close.

state.py reports which section failed, so you know which value to fix.
"""

# --- Per-version values ----------------------------------------------------
# state.py detects the running exe's version and calls use() to pick a profile.
# 1.2.0.1096 is the current Steam build: most board fields sit 0x18 later than
# in 1073, and zombie entries are larger.
PROFILES = {
    "1.2.0.1073": dict(BASE=0x6A9EC0, BOARD=0x768, SUN=0x5560,
                       ZOMBIE_ARRAY=0x90, ZOMBIE_MAX=0x94,
                       PLANT_ARRAY=0xAC, PLANT_MAX=0xB0, SEED_BANK=0x144,
                       ZOMBIE_SIZE=0x15C, COIN_ARRAY=0xE4, COIN_MAX=0xE8,
                       MOWER_ARRAY=0x100, MOWER_MAX=0x104, PAUSED=0x164,
                       WAVE_TOTAL=0x5564, WAVE_NOW=0x557C,
                       GAME_SCENE=0x7FC, DAVE_TALKING=None, GRID_TYPES=0x168),
    # Steam build (runs as popcapgame1.exe). Every value here was verified
    # against a live game on 2026-11-18.
    "1.2.0.1096": dict(BASE=0x731C50, BOARD=0x868, SUN=0x5578,
                       ZOMBIE_ARRAY=0xA8, ZOMBIE_MAX=0xAC,
                       PLANT_ARRAY=0xC4, PLANT_MAX=0xC8, SEED_BANK=0x15C,
                       ZOMBIE_SIZE=0x168, COIN_ARRAY=0xFC, COIN_MAX=0x100,
                       MOWER_ARRAY=0x118, MOWER_MAX=0x11C, PAUSED=0x17C,
                       WAVE_TOTAL=0x557C, WAVE_NOW=0x5594,
                       # on the main game object [BASE], not the board:
                       GAME_SCENE=0x91C, DAVE_TALKING=0x964,
                       # on the board: int[9 cols][6 rows] cell types (verified on the 1-1 tutorial)
                       GRID_TYPES=0x180),
}

# Values in GRID_TYPES
CELL_GRASS, CELL_DIRT, CELL_POOL, CELL_ROOF = 1, 2, 3, 4

# Values of GAME_SCENE
SCENES = {0: "loading", 1: "menu", 2: "intro", 3: "playing", 4: "zombies_won",
          5: "award", 6: "credits", 7: "challenge"}
VERSION = "1.2.0.1073"


def use(version):
    """Switch the module-level offsets to the profile for this exe version."""
    global VERSION
    if version not in PROFILES:
        raise KeyError(f"No offsets for version {version}. Known: {', '.join(PROFILES)}")
    VERSION = version
    globals().update(PROFILES[version])


# --- Root pointers (defaults = 1073; replaced by use()) ---------------------
BASE = 0x6A9EC0          # static pointer to the main game object
BOARD = 0x768            # [BASE] + BOARD -> pointer to the current level ("board"); 0 = not in a level

# --- Board fields (offset from board pointer) ------------------------------
SUN = 0x5560             # int

# Zombies: an array of fixed-size structs, some entries are dead/unused
ZOMBIE_ARRAY = 0x90      # pointer to first zombie struct
ZOMBIE_MAX = 0x94        # int, array capacity
ZOMBIE_SIZE = 0x15C
Z_ROW = 0x1C             # int
Z_TYPE = 0x24            # int (see ZOMBIE_NAMES in state.py)
Z_X = 0x2C               # float, screen x (≈ 800 at spawn, < 0 = reached house)
Z_HP = 0xC8              # int, body health
Z_ARMOR_HP = 0xD0        # int, cone/bucket/door health
Z_DEAD = 0xEC            # bool

# Plants: same pattern
PLANT_ARRAY = 0xAC
PLANT_MAX = 0xB0
PLANT_SIZE = 0x14C
P_ROW = 0x1C             # int
P_TYPE = 0x24            # int (see PLANT_NAMES in state.py)
P_COL = 0x28             # int
P_HP = 0x40              # int
P_DEAD = 0x141           # bool

# Seed bank (the packets along the top)
SEED_BANK = 0x144        # pointer
SB_COUNT = 0x24          # int, number of slots this level
SB_FIRST_CARD = 0x28     # first card struct inside the seed bank
CARD_SIZE = 0x50
C_RECHARGE_NOW = 0x24    # int, counts up while recharging   (LEAST certain: verify)
C_RECHARGE_MAX = 0x28    # int
C_TYPE = 0x34            # int, plant type id
C_USABLE = 0x48          # bool, true when off cooldown
# Sun / coins (falling sun, sunflower sun, money)
COIN_SIZE = 0xD8
CO_X = 0x24              # float, top-left of a 60x60 box
CO_Y = 0x28              # float
CO_DEAD = 0x38           # bool
CO_COLLECTED = 0x50      # bool, already clicked and flying to the bank
CO_TYPE = 0x58           # int: 1 silver, 2 gold, 3 diamond, 4 sun, 5 small sun, 6 big sun
SUN_TYPES = {4: 25, 5: 15, 6: 50}
MONEY_TYPES = {1, 2, 3}
# 7 final seed packet, 8 trophy, 9 shovel, 10 almanac, 11 car keys, 12 vase, 13 watering can,
# 14 taco, 15 note, 17-25 presents / money bag / chocolate / silver & gold sunflower trophies
AWARD_TYPES = {7, 8, 9, 10, 11, 12, 13, 14, 15} | set(range(17, 26))

# Lawn mowers
MOWER_SIZE = 0x48
M_ROW = 0x14             # int
M_DEAD = 0x30            # bool, true once used up

# Board flags (PAUSED, WAVE_* are per-version, above)
# PAUSED is the space-bar pause; the "Game Paused" focus-loss dialog is separate.

# Screen rectangles (game pixels): seed bank is absolute, cards are relative to the bank
OBJ_X, OBJ_Y, OBJ_W, OBJ_H = 0x08, 0x0C, 0x10, 0x14

# Lawn layout (Day/Night levels: 5 rows x 9 cols; Pool/Fog have 6 rows)
ROWS = 5
COLS = 9
