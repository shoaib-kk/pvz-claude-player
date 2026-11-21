# Voiceover script: "This AI Lost the Same Level 11 Times. Then It Read Its Own Diary."

Format: voiceover only, dry documentary tone. About 1,170 spoken words: about 8.5 minutes with pauses for the visual beats.
**VISUAL** = what's on screen. **VO** = what you say. *On-screen text* = Claude's own words
from the logs, shown but not read out unless marked.
`[NEED]` marks footage that only exists as a screenshot so far.

All quotes are real lines from `journal_sonnet/lessons.json` and `logs/`.

---

## 0:00 Cold open

**VISUAL:** 4-1 "The zombies ate your brains" screen. Hard cuts through four more loss screens
(`logs/*_level_31_lost_*.png`), a little faster each time.

**VO:** This AI lost this level eleven times in a row.

**VISUAL:** Slow push in on a diary page. One line is highlighted:
*"Skip puff_shroom; spend on fumes and walls."*

**VO:** And the problem wasn't the zombies. It was this line. The AI wrote it in its own diary,
after studying its own losses. It's a rule it made up, and it's wrong.

**VISUAL:** Puff-shroom seed card. Price tag: **0 sun**.

**VO:** The puff-shroom is free. It had banned the only free plant on the board.

**VISUAL:** Cut to the winning 4-1 board, with puff-shrooms in every row. `[NEED]` gameplay clip.

**VO:** I didn't give it the answer. I showed it its own history. It won on the very next try.
This is how an AI that can't even see the screen learned to play Plants vs. Zombies, and how it
learned some of the wrong things too.

---

## 0:45 How it sees the game

**VISUAL:** `docs/how-it-works.gif`, full screen.

**VO:** First, what's actually playing. The AI is Claude. It never sees a single pixel of the
game. Instead, a script reads the game's memory, about seven times a second, and turns the lawn
into text.

**VISUAL:** Split screen. Left: the game. Right: the text board from a log, scrolling slowly,
with "row 0 M: sunflower|.|.|Z:zombie..." highlighted.

**VO:** Sun, seeds, every plant, every zombie, all written out like a spreadsheet. Claude reads
that, and answers with a short to-do list. Plant this here. Then that there. The script does all
the clicking.

**VISUAL:** The overlay showing a reasoning line and the queued plants ticking off.

**VO:** It isn't asked every frame. It's asked when something changes: a new zombie, a plant
getting eaten, a lawn mower firing. Each answer takes it about two or three seconds, and the game
doesn't pause while it thinks.

**VISUAL:** Stat card: **"Asked: when something changes. Thinks: ~2–3 s. Game: never paused."**

**VO:** So that's the body. The interesting part is the brain.

---

## 1:35 Rules, not strategy

**VISUAL:** A plant card from `plant_info.py`, e.g. *"Free mushroom that shoots short-range
spores."*

**VO:** Here's the one rule I set for this project. The AI gets told what things do, never what
to do. It knows a puff-shroom is free and short-range. It does not know where to put it, or
whether it's any good.

**VISUAL:** An empty journal page, then the first entries appearing line by line.

**VO:** Everything else it has to learn. After every level, win or lose, it gets a plain
timeline of what happened: what it brought, what got eaten, which mowers fired. Then it rewrites
its own diary. Up to twenty general lessons, plus ten for each kind of level. That diary goes
into every decision it makes from then on.

**VISUAL:** Highlight an early lesson:
*"Fume_shroom in cols 3-4 of each row was the main killer; get one in every row that zombies use."*

**VO:** Some early lessons were good. This one is basically how humans play night levels.

**VO:** The thing is, it doesn't know which of its lessons are good. Neither do I, until it plays.

---

## 2:35 World 2: night

**VISUAL:** Night lawn, graves, sun-shrooms. `[NEED]` a clip from World 2.

**VO:** Night levels are the first real test. No sun falls from the sky. Your only income is
what you plant. An early version of this setup lost level 2-3 six times in a row, mostly by
spending its sun on plants that got eaten before they paid for themselves.

**VISUAL:** Level strip graphic: **2-3 W · 2-4 L W · 2-5 W · 2-6 L L W · 2-7 W · 2-8 W · 2-9 W · 2-10 W**

**VO:** With the diary running, it got through the rest of World 2 losing only three times in
eight levels. The lessons were doing something.

**VO:** Then I added water.

---

## 3:05 World 3: the pool

**VISUAL:** Pool lawn, six rows, lily pads. `[NEED]` 3-1 clip.

**VO:** The pool adds two rows down the middle where land plants can't go without a lily pad
underneath. And on the first three pool levels, it did exactly the same thing three times.

**VISUAL:** Strip: **3-1 L L W · 3-2 L L W · 3-3 L L W**

**VO:** Lose. Lose. Win. Every time.

**VISUAL:** 3-1 first-loss summary on screen:
*"Row 3 (water) was never built up: it had zero plants at the end..."*

**VO:** Here's the first loss on 3-1, in its own words. It just didn't defend the water.

**VISUAL:** 3-1 win summary:
*"...giving every row, water rows included, 2 or more peashooters. All 6 mowers were still
ready at wave 10."*

**VO:** Two losses later: every row gets defended, the water included. Not one lawn mower used.
That's the loop working the way it's supposed to. Fail, write it down, fix it.

**VO:** And then it walked into the fog, and the loop broke.

---

## 3:50 4-1: the superstition

**VISUAL:** 4-1 fog rolling over the right half of the lawn.

**VO:** Level 4-1. It's night, so no falling sun. There's a pool. And there's fog, so you can't
see what's coming. You need cheap defence fast, and the game hands you exactly that: the
puff-shroom. It costs nothing.

**VISUAL:** Montage of journal lessons, one per loss, each appearing over the last:
- *"Puff_shrooms alone can't stop coneheads, and 8 of them died uselessly."*
- *"Don't spend early sun on cheap puffs; save it for fumes plus nuts."*
- *"Skip puff_shroom; spend on fumes and walls."*

**VO:** Puff-shrooms are small. They die a lot. And every time it lost, its report said things
like "puff-shroom, destroyed, times fourteen." So it drew the obvious conclusion: these things are
useless. It wrote it down, then wrote it down harder, then made it a rule.

**VO:** Free plants that die cost you nothing. But nothing in the report said that. It just
counted bodies.

**VISUAL:** Stat card, two columns:
**With puff-shroom: 14–39 plants placed per attempt**
**Without: 5–7**

**VO:** Here's what the rule actually did. When it brought puff-shrooms, it filled the lawn.
After it banned them, it was placing five, six, seven plants in an entire level, while sitting on
unspent sun waiting for the expensive ones.

**VISUAL:** Loss counter ticking up to **11**.

**VO:** Eleven losses. Each one, it looked back at the evidence and found a new reason. Never
the real one.

---

## 5:00 The fix

**VISUAL:** Side by side: the old report line vs the new one.
Old: *"Plants destroyed by zombies: puff_shroom x14"*
New: *"Plants destroyed by zombies: puff_shroom x14 (0 sun each). Sun value of plants destroyed: ..."*

**VO:** So how do you fix an AI that believes something wrong? The easy way is to just tell it:
use puff-shrooms. But then it isn't learning. It's me playing through it.

**VO:** So I changed what it sees, not what it thinks. Two things. First, every dead plant now
comes with its price. Fourteen dead puff-shrooms, zero sun each.

**VISUAL:** The earlier-attempts table, one line per attempt, with loadout, wave and plants placed.

**VO:** Second, when it looks back at a level, it now sees every earlier attempt at that level
side by side. What it brought, how far it got, how much it actually built.

**VO:** And I took the bad rule out of its diary. That part was me, and it's the one place I
stepped in, because otherwise it would have walked into the next attempt still believing it.

**VISUAL:** Pick screen: puff-shroom AND sea-shroom chosen. Then the 4-1 win. `[NEED]` gameplay.

**VO:** Next attempt. It picks the puff-shroom. It also picks the sea-shroom, the other free
plant, the one that sits straight on water. Twenty-seven plants on the board. Wave ten of ten.
Five of six lawn mowers still parked.

**VISUAL:** The new lesson highlighted:
*"Use free puff_shroom (0 sun) as the first shooter in every row while sun is scarce."*

**VO:** And the rule in its diary now says the opposite of what it said an hour earlier.

---

## 6:20 Balloons, and the vases

**VISUAL:** 4-3, a balloon zombie floating over the plants.

**VO:** The fog wasn't done with it. Level 4-3 brought balloon zombies, which float over
everything. Only a few plants can touch them. It knew that, and brought a cactus. It just kept not
planting it. That took a few tries.

**VISUAL:** 4-5, the lawn full of vases.

**VO:** Then 4-5, Vasebreaker. There's no sun here. The lawn is full of vases, and each one has
either a zombie or a free plant inside.

**VISUAL:** Freeze-frame of the stuck board. On-screen text:
*"No zombies yet; wait and keep the queue empty until the next board."*

**VO:** And it decided the right move was to wait for the zombies to show up. In a mode where
zombies only come out when you break a vase.

**VO:** So it waited. And the game waited. And nothing happened, for a very long time.

**VISUAL:** 4-5 loss summary:
*"I opened many vases in a row without clearing the zombies, so they overran all rows."*

**VO:** Once it got going, it overcorrected. It smashed everything at once and got swarmed. Twice.

**VISUAL:** 4-5 win summary:
*"I won by breaking vases one at a time and planting each free shooter... in cols 0-3."*

**VO:** Third try: one vase at a time. Plant whatever comes out. Then the next one. Which is,
again, how a person would figure it out.

---

## 7:25 Finishing World 4

**VISUAL:** Fast montage of 4-6 to 4-10, with the strip graphic filling in:
**4-6 W · 4-7 W · 4-8 W · 4-9 L W · 4-10 L W**

**VO:** After that, World 4 fell quickly. Three straight wins. A balloon zombie got through on
4-9 because the only cactus went in too late. It fixed that the next attempt.

**VISUAL:** 4-10 conveyor belt.

**VO:** And the last level threw away its plans completely, with a conveyor belt of random plants,
so the diary's night-level strategy was useless. It lost once, adapted to whatever the belt gave
it, and won.

**VISUAL:** Full progress strip from 2-3 to 4-10.

**VO:** Thirty levels. Most of them won first try. The ones that weren't are where it learned
something. Including, once, something wrong.

---

## 8:00 Ending, and what's next

**VISUAL:** Slow scroll through the current diary.

**VO:** I think that's the most interesting thing about it. Not that it wins. It's that it
learns the way people do, from what it sees happen. And when what it sees is misleading, it
learns the wrong lesson just as confidently.

**VO:** The fix wasn't more rules. It was better evidence.

**VISUAL:** World 5 roof, then the shadow of Zomboss.

**VO:** Next up: the roof, where plants need pots and nothing shoots straight. And at the end of
it, Dr. Zomboss. Let's see what it writes in the diary about him.

**VISUAL:** End screen: the next episode and the series playlist.

---

## Notes for recording

- About 1,170 words. At about 150 words a minute plus pauses that's roughly 8.5 minutes, inside
  the 8–15 minute range. Don't pad it to reach a longer length. If you want more, the best place
  to add is real 4-1 footage, not more narration.
- `[NEED]` clips: the World 2 night level, 3-1, the 4-1 win, 4-3 balloons, 4-5 and the World 4
  montage. If there's no recording, replay those levels with the overlay on, or use the screenshots
  with slow zooms.
- Re-check every number against the journal right before recording if more levels get played.
- **Line to check:** "An early version of this setup lost level 2-3 six times in a row." That
  comes from the first journal (`journal/`), before the Sonnet journal started. Confirm which
  model that was if you name it.
- The fix section says "I took the bad rule out of its diary." Keep that line in: it's the honest
  version, and it's the one place the operator stepped in.
