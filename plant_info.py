"""What the player is allowed to know about each plant.

Two stages, mirroring a human's first playthrough:
  * CARDS - one line per plant, like the "You got a new plant!" card and seed packet.
    Known from the start.
  * ALMANAC - stats like the Suburban Almanac's (cost, recharge, damage, range,
    toughness, quirks). A human unlocks the Almanac by beating Adventure 2-4, so the
    player only gets these from level 2-5 (absolute level 15) on.

All descriptions are our own wording of the game's mechanics, not the game's text.
These are facts about plants, not advice on how to use them; the player works out
strategy itself (see journal.py).
"""

ALMANAC_FROM_LEVEL = 15     # 2-5: the first level after the 2-4 Almanac reward

CARDS = {
    "peashooter": "Shoots peas at zombies in its row.",
    "sunflower": "Produces extra sun.",
    "cherry_bomb": "Explodes, destroying zombies in a small area around it.",
    "wall_nut": "A tough shell that blocks zombies.",
    "potato_mine": "Explodes on the first zombie that touches it, but needs time to arm.",
    "snow_pea": "Shoots frozen peas that damage and slow zombies.",
    "chomper": "Swallows a zombie whole, then must chew for a while.",
    "repeater": "Shoots two peas at a time.",
    "puff_shroom": "Free mushroom that shoots short-range spores.",
    "sun_shroom": "Mushroom that gives a little sun at first and more once grown.",
    "fume_shroom": "Mushroom that sprays fumes through every zombie in a short range.",
    "grave_buster": "Planted on a grave to remove it.",
    "hypno_shroom": "A zombie that eats it turns around and fights for you.",
    "scaredy_shroom": "Long-range mushroom that hides when zombies get close.",
    "ice_shroom": "Freezes every zombie on the screen for a while.",
    "doom_shroom": "Huge explosion over a wide area; leaves a crater.",
    "lily_pad": "Floats on water so other plants can be placed on it.",
    "squash": "Crushes the first zombie that comes near it.",
    "threepeater": "Shoots peas in three rows at once.",
    "tangle_kelp": "Water plant that drags a zombie underwater.",
    "jalapeno": "Burns every zombie in its row.",
    "spikeweed": "Hurts zombies that walk over it; can't be eaten.",
    "torchwood": "Peas that pass through it catch fire and do more damage.",
    "tall_nut": "A very tough wall that zombies can't jump over.",
    "sea_shroom": "Water mushroom that shoots short-range spores.",
    "plantern": "Lights up the fog around it.",
    "cactus": "Shoots spikes that can pop balloons.",
    "blover": "Blows away the fog and all flying zombies.",
    "split_pea": "Shoots peas forward and backward.",
    "starfruit": "Shoots stars in five directions.",
    "pumpkin": "A shell placed over another plant to protect it.",
    "magnet_shroom": "Pulls metal objects (helmets, ladders...) off zombies.",
    "cabbage_pult": "Lobs cabbages over obstacles at zombies.",
    "flower_pot": "A pot that lets plants be placed on the roof.",
    "kernel_pult": "Lobs kernels, or butter that stops a zombie briefly.",
    "coffee_bean": "Wakes up a sleeping mushroom.",
    "garlic": "Zombies that bite it switch to another row.",
    "umbrella_leaf": "Protects nearby plants from things dropped or thrown from above.",
    "marigold": "Produces coins.",
    "melon_pult": "Lobs heavy melons that also splash nearby zombies.",
    "gatling_pea": "Shoots four peas at a time. Upgrade: plant on a Repeater.",
    "twin_sunflower": "Produces twice the sun. Upgrade: plant on a Sunflower.",
    "gloom_shroom": "Sprays fumes all around itself. Upgrade: plant on a Fume-shroom.",
    "cattail": "Water plant that shoots spikes at any zombie on the lawn. Upgrade: plant on a Lily Pad.",
    "winter_melon": "Lobbed melons that slow zombies. Upgrade: plant on a Melon-pult.",
    "gold_magnet": "Collects coins. Upgrade: plant on a Magnet-shroom.",
    "spikerock": "Tougher spikes that last longer. Upgrade: plant on a Spikeweed.",
    "cob_cannon": "Fires a huge corn missile where you aim. Upgrade: plant on two Kernel-pults.",
    "explode_o_nut": "A nut that explodes when it hits a zombie.",
    "giant_wall_nut": "A huge nut that flattens zombies in its path.",
}

# Recharge: fast ~7.5 s, slow ~30 s, very slow ~50 s. Damage: "normal" is one pea (20).
# Toughness: a typical plant survives about 300 bites of damage.
ALMANAC = {
    "peashooter": "recharge fast; damage normal; range whole row ahead",
    "sunflower": "recharge fast; +25 sun about every 24 s",
    "cherry_bomb": "recharge very slow; damage massive; 3x3 area around it; instant",
    "wall_nut": "recharge slow; toughness high (~13x a normal plant)",
    "potato_mine": "recharge slow; damage massive; one tile; arms about 15 s after planting, harmless before",
    "snow_pea": "recharge fast; damage normal; range whole row; slows hit zombies",
    "chomper": "recharge fast; eats one zombie in the tile directly ahead; ~42 s to chew, defenceless meanwhile",
    "repeater": "recharge fast; damage normal x2; range whole row",
    "puff_shroom": "recharge fast; damage normal; range only 3 tiles ahead; sleeps in daytime",
    "sun_shroom": "recharge fast; +15 sun, rising to +25 after ~2 min; sleeps in daytime",
    "fume_shroom": "recharge fast; damage normal; hits all zombies up to 4 tiles ahead, through screen doors; sleeps in daytime",
    "grave_buster": "recharge fast; only on graves; removes it after a few seconds; sleeps in daytime",
    "hypno_shroom": "recharge slow; the zombie that eats it fights for you; sleeps in daytime",
    "scaredy_shroom": "recharge fast; damage normal; range whole row; stops shooting while a zombie is within ~1 tile; sleeps in daytime",
    "ice_shroom": "recharge very slow; freezes all zombies on screen; sleeps in daytime",
    "doom_shroom": "recharge very slow; damage massive; large radius; leaves a crater that blocks planting; sleeps in daytime",
    "lily_pad": "recharge fast; water only; holds one non-water plant",
    "squash": "recharge slow; damage massive; hits a zombie in its own or the adjacent tile",
    "threepeater": "recharge fast; damage normal; its row and both neighbouring rows",
    "tangle_kelp": "recharge slow; water only; removes one zombie",
    "jalapeno": "recharge very slow; damage massive; whole row; instant",
    "spikeweed": "recharge fast; damage normal to zombies on it; can't be eaten; pops vehicle tyres (and is destroyed)",
    "torchwood": "recharge fast; peas passing through do double damage",
    "tall_nut": "recharge slow; toughness very high (~26x a normal plant); blocks jumping zombies",
    "sea_shroom": "recharge slow; water only; range 3 tiles ahead; sleeps in daytime",
    "plantern": "recharge slow; clears fog in a radius",
    "cactus": "recharge fast; damage normal; range whole row; hits balloon zombies",
    "blover": "recharge fast; one use; removes fog briefly and blows away flying zombies",
    "split_pea": "recharge fast; damage normal forward, x2 backward",
    "starfruit": "recharge fast; damage normal; five diagonal and straight directions",
    "pumpkin": "recharge slow; toughness high; placed over a plant, absorbs bites first",
    "magnet_shroom": "recharge fast; removes one metal item, then recharges itself; sleeps in daytime",
    "cabbage_pult": "recharge fast; damage double; lobbed, so it passes over shields; whole row",
    "flower_pot": "recharge fast; roof only; holds one plant",
    "kernel_pult": "recharge fast; damage normal; lobbed; sometimes butter that stops a zombie a few seconds",
    "coffee_bean": "recharge fast; wakes the mushroom it's placed on",
    "garlic": "recharge fast; toughness moderate; diverts a biting zombie to a neighbouring row",
    "umbrella_leaf": "recharge fast; protects its 3x3 area from bungee and catapult attacks",
    "marigold": "recharge slow; drops coins, no sun",
    "melon_pult": "recharge fast; damage heavy (4x) with splash; lobbed; whole row",
    "gatling_pea": "recharge very slow; damage normal x4; whole row",
    "twin_sunflower": "recharge very slow; +50 sun at a time",
    "gloom_shroom": "recharge very slow; damage heavy; all eight surrounding tiles; sleeps in daytime",
    "cattail": "recharge very slow; damage normal; homes in on any zombie, including balloons",
    "winter_melon": "recharge very slow; damage heavy with splash; slows",
    "gold_magnet": "recharge very slow; collects coins",
    "spikerock": "recharge very slow; damage double; survives several vehicles",
    "cob_cannon": "recharge very slow; damage massive in a 3x3 area anywhere; reloads ~35 s after firing",
}


def describe_plants(names, level=None):
    """Lines describing each named plant at the knowledge stage for `level`."""
    almanac = level is not None and level >= ALMANAC_FROM_LEVEL
    lines = []
    for name in dict.fromkeys(names):
        if name not in CARDS:
            continue
        info = CARDS[name]
        if almanac and name in ALMANAC:
            info += f" [Almanac: {ALMANAC[name]}]"
        lines.append(f"  {name}: {info}")
    return lines


def stage(level):
    return "almanac" if level is not None and level >= ALMANAC_FROM_LEVEL else "cards"
