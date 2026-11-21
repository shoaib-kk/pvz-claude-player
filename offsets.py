"""Memory layouts for the original and Steam GOTY builds.

The existing day-lawn fields were verified on Steam 1.2.0.1096. The additional
Adventure, grid item, tutorial, and boss fields follow the public reference at
https://github.com/Patoke/re-plants-vs-zombies/tree/main/Lawn and need live
verification. state.py reports section errors when a read fails.
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
                       GAME_SCENE=0x7FC, DAVE_TALKING=None, GRID_TYPES=0x168,
                       GRID_ITEM_ARRAY=0x11C, GRID_ITEM_MAX=0x120, FIREBALL_ROW=0x148),
    # Steam build (runs as popcapgame1.exe). The original day-lawn offsets were
    # verified on 2026-11-18. GRID_ITEM_* and FIREBALL_ROW are inferred additions.
    "1.2.0.1096": dict(BASE=0x731C50, BOARD=0x868, SUN=0x5578,
                       ZOMBIE_ARRAY=0xA8, ZOMBIE_MAX=0xAC,
                       PLANT_ARRAY=0xC4, PLANT_MAX=0xC8, SEED_BANK=0x15C,
                       ZOMBIE_SIZE=0x168, COIN_ARRAY=0xFC, COIN_MAX=0x100,
                       MOWER_ARRAY=0x118, MOWER_MAX=0x11C, PAUSED=0x17C,
                       WAVE_TOTAL=0x557C, WAVE_NOW=0x5594,
                       # on the main game object [BASE], not the board:
                       GAME_SCENE=0x91C, DAVE_TALKING=0x964,
                       # on the board: int[9 cols][6 rows] cell types (verified on the 1-1 tutorial)
                       GRID_TYPES=0x180, GRID_ITEM_ARRAY=0x134, GRID_ITEM_MAX=0x138,
                       FIREBALL_ROW=0x14C),
}

# Value 4 is high ground. Roof geometry is selected from the background field.
CELL_GRASS, CELL_DIRT, CELL_POOL, CELL_ROOF = 1, 2, 3, 4
BACKGROUNDS = ("day", "night", "pool", "fog", "roof", "boss")
ADVENTURE_CONVEYORS = {5, 10, 20, 25, 30, 40, 45, 50}
ADVENTURE_SPECIALS = {5: "bowling", 15: "whack", 35: "vases", 50: "boss"}

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
Z_PHASE = 0x28
Z_BOSS_PROJECTILE = 0x140
FIREBALL_ROW = 0x148

# Plants: same pattern
PLANT_ARRAY = 0xAC
PLANT_MAX = 0xB0
PLANT_SIZE = 0x14C
P_ROW = 0x1C             # int
P_TYPE = 0x24            # int (see PLANT_NAMES in state.py)
P_COL = 0x28             # int
P_HP = 0x40              # int
P_DEAD = 0x141           # bool
P_ASLEEP = 0x143

# Seed bank (the packets along the top)
SEED_BANK = 0x144        # pointer
SB_COUNT = 0x24          # int, number of slots this level
SB_FIRST_CARD = 0x28     # first card struct inside the seed bank
CARD_SIZE = 0x50
C_RECHARGE_NOW = 0x24    # int, counts up while recharging   (LEAST certain: verify)
C_RECHARGE_MAX = 0x28    # int
C_OFFSET_X = 0x30        # horizontal conveyor motion relative to the slot
C_TYPE = 0x34            # int, plant type id
C_USABLE = 0x48          # bool, true when off cooldown
# Sun / coins (falling sun, sunflower sun, money)
COIN_SIZE = 0xD8
CO_X = 0x24              # float, top-left of a 60x60 box
CO_Y = 0x28              # float
CO_DEAD = 0x38           # bool
CO_COLLECTED = 0x50      # bool, already clicked and flying to the bank
CO_TYPE = 0x58           # int: 1 silver, 2 gold, 3 diamond, 4 sun, 5 small sun, 6 big sun
CO_SEED = 0x68           # seed type carried by a temporary seed packet
CO_AGE = 0x4C            # elapsed game ticks (100 ticks ~= 1 second)
CO_DISAPPEAR = 0x54      # ticks spent on the ground before fading
CO_FADE = 0x3C
USABLE_SEED_PACKET = 16
VASE_PACKET_LIFETIME = 1500  # Coin::GetDisappearTime; estimate at normal game speed
SUN_TYPES = {4: 25, 5: 15, 6: 50}
MONEY_TYPES = {1, 2, 3}
# 7 final seed packet, 8 trophy, 9 shovel, 10 almanac, 11 car keys, 12 vase, 13 watering can,
# 14 taco, 15 note, 17-25 presents / money bag / chocolate / silver & gold sunflower trophies
AWARD_TYPES = {7, 8, 9, 10, 11, 12, 13, 14, 15} | set(range(17, 26))

# Lawn mowers
MOWER_SIZE = 0x48
M_ROW = 0x14             # int
M_DEAD = 0x30            # bool, true once used up

# Grid item layout follows the Board/DataArray and GridItem definitions in
# https://github.com/Patoke/re-plants-vs-zombies/tree/main/Lawn
GRID_ITEM_ARRAY = 0x11C
GRID_ITEM_MAX = 0x120
GRID_ITEM_SIZE = 0xEC
GI_TYPE, GI_COL, GI_ROW, GI_DEAD = 0x08, 0x10, 0x14, 0x20
GI_STATE = 0x0C          # visible vase sprite; plain=3 verified live on GOTY 2026-11-20
# Appearance enums follow ConstEnums.h; concealed content fields 0x3C-0x44 are never decoded.
VASE_APPEARANCES = {3: "plain", 4: "plant", 5: "zombie"}
GRID_ITEMS = {1: "grave", 2: "crater", 7: "vase"}

# Board flags (PAUSED, WAVE_* are per-version, above)
# PAUSED is the space-bar pause; the "Game Paused" focus-loss dialog is separate.

# Screen rectangles (game pixels): seed bank is absolute, cards are relative to the bank
OBJ_X, OBJ_Y, OBJ_W, OBJ_H = 0x08, 0x0C, 0x10, 0x14

# Lawn layout (Day/Night levels: 5 rows x 9 cols; Pool/Fog have 6 rows)
ROWS = 5
COLS = 9

# Initialize every profile field for callers using the default layout.
use(VERSION)
