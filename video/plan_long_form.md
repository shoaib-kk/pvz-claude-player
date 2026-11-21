# Long-form video plan: Claude plays Plants vs. Zombies

Working premise: an AI that can't see the screen plays Adventure mode, keeps a diary of its own
lessons, and has to learn the game by losing. The emotional spine is **"it got superstitious, and
the fix was giving it its own history, not the answer."**

All numbers below come from `journal_sonnet/lessons.json` and `logs/`. Re-check them before
recording if more levels are played. No YouTube metrics are assumed or invented here.

---

## 1. Packaging first (C: Click)

Decide the title and thumbnail before scripting; the cold open has to pay off exactly this promise.

**Title options** (pick one, A/B test two in Studio):
1. *I Gave an AI a Diary and Let It Play Plants vs. Zombies*
2. *This AI Lost the Same Level 11 Times. Then It Read Its Own Diary.*
3. *AI Plays Plants vs. Zombies and Gets Superstitious*

**Thumbnail concept** (one idea, three elements max):
- Foggy night lawn from 4-1, zombies coming out of the fog.
- A handwritten diary page in front with **"Skip puff-shroom"** crossed out in red.
- Big text: **11 LOSSES** (or no text, letting the crossed-out line carry it).

Clarity check: someone scrolling should understand "AI + PvZ + it was wrong about something"
in under a second. Avoid clutter (no seed bank, no UI chrome).

---

## 2. Hook: first 30 seconds (H)

Open on the payoff, not the setup.

> **[0:00]** Footage: 4-1 loss screen, then a quick montage of losses (use the
> `*_level_31_lost_*.png` screenshots).
> **VO:** "This AI lost this level eleven times in a row. And the reason wasn't the zombies.
> It had written itself a rule — in its own diary — and the rule was wrong."
> **[0:12]** Zoom on the journal line: *"Skip puff_shroom; spend on fumes and walls."*
> **VO:** "Puff-shrooms are free. It had banned the only free plant in the game."
> **[0:20]** Cut to the winning 4-1 board with puffs everywhere.
> **VO:** "I didn't tell it the answer. I showed it its own history. It won the next try.
> Here's how an AI that can't even see the screen learned to play Plants vs. Zombies."

No logo, no "hey guys"; the channel intro, if any, goes after 0:30.

---

## 3. Structure: re-hook every 60–90 s (A)

Target about 8–9 minutes (the script runs about 1,170 words). Cut anything that doesn't move the story.

| Time | Chapter | Beat | Re-hook at the end |
|---|---|---|---|
| 0:00 | Cold open | 4-1 loss streak, the wrong rule, the win | "...here's how it works." |
| 0:45 | How it sees the game | It reads game memory as text, never pixels; answers with a to-do list; a script does the clicking. Use `docs/how-it-works.gif`. | "But it starts every level knowing nothing about strategy." |
| 1:35 | Rules, not strategy | It's told what plants do, never what to do. After every level it writes its own lessons. Show the first journal entries. | "And its first lessons were terrible." |
| 2:35 | World 2: night | Early losses on 2-3 (mushrooms, no falling sun), first real wins. Lessons getting better. | "Then we added water." |
| 3:05 | World 3: the pool | 3-1, 3-2 and 3-3 each went **lose, lose, win**. Show the pattern: it really learns from losing. | "Then came the fog." |
| 3:50 | 4-1: the superstition | 11 losses. Free puff-shrooms kept dying, so it decided they were useless. Show the lesson hardening across reflections. Key stat: with puffs it placed **14–39 plants** per attempt; without them, **5–7**. | "So how do you fix an AI that believes something wrong?" |
| 5:00 | The fix | Not the answer: its own history. A table of every earlier attempt, plus the sun cost next to each dead plant ("puff-shroom ×14, 0 sun each"). Next try: **won, 5 of 6 mowers kept**. Its new lesson: *"Use free puff_shroom as the first shooter in every row."* | "But the fog wasn't done with it." |
| 6:20 | 4-3 to 4-5 | Balloon zombies over the water; then Vasebreaker, where it decided *"No zombies yet; wait"* with four vases left, and the game waited with it. | "Then something clicked." |
| 7:25 | 4-6 to 4-10 | Win streak through the rest of World 4. Montage. | Setup for NEXT. |
| 8:00 | Ending + NEXT | Where it stands, the roof is next, Zomboss at 5-10. | End screen. |

Keep one topic: **an AI learning from its own mistakes.** Haiku vs Sonnet, token costs and code
details are a different video (see NEXT).

---

## 4. Iterate: what to watch after publishing (I)

Read these three numbers in Studio (they aren't known yet):
- **CTR**: the packaging. If it's low but retention is good, change the thumbnail or title first.
- **30-second retention**: the hook. If people leave early, the cold open isn't delivering the title.
- **Average view duration %**: the structure. Look for the dip in the retention graph and cut there.

Change one variable at a time.

---

## 5. Next: keep the session going (N)

- **End screen:** "Can it beat Zomboss?" (the World 5 / roof video). Film it as the next episode.
- **Series playlist:** "AI plays Plants vs. Zombies", with this as episode 1.
- **Natural sequel:** *Cheap AI vs smart AI*. `journal_haiku_from_sonnet` reached 4-1 on the
  same levels, so Haiku vs Sonnet is a ready-made episode 2.
- **Shorts to cut from this** (each linking to the long video):
  - "AI banned the only free plant" (the 4-1 story in 45 s)
  - "AI waits forever in Vasebreaker"
  - "How an AI reads Plants vs. Zombies" (the GIF explainer)

---

## 6. Description + chapters (Search)

> An AI (Claude) plays Plants vs. Zombies Adventure mode. It can't see the screen: it reads the
> game as text and keeps a diary of lessons it writes itself. On level 4-1 it lost 11 times in a
> row because of one wrong rule in that diary.
>
> 0:00 The level it lost 11 times
> 0:45 How an AI sees Plants vs. Zombies
> 1:35 Rules, not strategy
> 2:35 World 2: night levels
> 3:05 World 3: the pool
> 3:50 Level 4-1: the superstition
> 5:00 The fix
> 6:20 Balloons and Vasebreaker
> 7:25 Finishing World 4
> 8:00 What's next

Update the timestamps after the edit. Add captions (auto, then corrected).

---

## 7. Production checklist

- [ ] Record clean gameplay for the 4-1 win and a couple of losses (screenshots exist; video
      needs re-recording or screen-capture logs, if you have them).
- [ ] Screen-capture the journal (`journal_sonnet/lessons.md`) at the key moments: the
      "Skip puff_shroom" line, and the corrected lesson after the win.
- [ ] Recording overlay with Claude's explanation on screen (it already exists in the project).
- [ ] Disclosure: the gameplay is real. If you add AI-generated B-roll or an AI voiceover, mark
      it as altered or synthetic content in Studio.
- [ ] Mention that the AI is Claude, and that you built the harness.

## Format: voiceover only

With no face on screen, the picture has to carry every second, and the voice carries the personality.
- **Script length:** at a natural 140–160 words a minute, the script's 1,170 words
  come to about 8.5 minutes. Don't pad it to reach a longer length.
- **Visual for every line.** Each script line needs something on screen: gameplay, Claude's
  on-screen explanation overlay, a journal close-up, a log stat, or a simple diagram. If a line
  has no visual, cut the line or make one.
- **Claude's words on screen.** Its reasoning quotes ("No zombies yet; wait") work like a second
  character. Show them as text overlays, and don't read them all aloud.
- **Pattern breaks** instead of face-cam cutaways: zoom on the journal, freeze-frame on a mistake,
  a quick stat card (e.g. "39 plants vs 6"), then back to gameplay.
- **Audio:** record the VO in one session with the same mic and room, then add light game audio
  underneath. Voice clarity matters more than anything else when there's no face cam.
- **If you use an AI voice** instead of your own, mark it as synthetic content in Studio.

## Still needed from you
- Tone: curious documentary, or jokey? The cold-open lines read as dry documentary for now.
- Whether you have gameplay recordings of the runs, or only the screenshots.
