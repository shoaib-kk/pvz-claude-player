# Development timeline

What changed, when, and why, for use in the video. Times are local to Sydney.
Haiku played the early runs. Sonnet took over at 2-3. The numbers come from the run logs.

## Before this session
- **Commit `ef40b1b`**: published the Claude PvZ player and its setup guide.
- **Commit `4b460d1`**: refocused the README on the gameplay loop.
- **Commit `70434f9`**: added Adventure mechanics, including conveyors, bowling, night, pool, roof and Zomboss, plus level-to-level navigation. These were tested offline only and had never run in the live game.

## 19 November: live test through Adventure 1-10

| Time | Level | What happened | Change made |
| --- | --- | --- | --- |
| 10:15 | 1-3 | The saved game was resumed, but a "Continue game?" dialog was still blocking the lawn. Four plantings failed. | The dialog is now detected and dismissed before play starts. |
| 10:19 | 1-3 | Plants went down, but no sun was collected, so the player was stuck on 0 sun. | Fixed the sun pickup filter, which was checking a field that reads 0 on this game version. Added a regression test. |
| 10:21–10:25 | 1-3 | **Won**: 16 decisions and 0 failed clicks. Reward: Wall-nut. | Added a screenshot after each win or loss as evidence. |
| 10:26 | — | The owner asked for every non-gameplay screen to be automated. | Scripted bot handling for menus, Continue, rewards, Crazy Dave, tutorials and Next Level. Claude now only picks plants and plays. |
| 10:26 | 1-4 intro | The mouse reached the bottom-left corner, which triggered the stop switch. | Pause dialogs caused by focus loss during intros are now handled. Added `--until-level N`. |
| 10:28–10:33 | 1-4 | **Won**: 25 decisions with all 5 mowers still intact. Reward: Shovel. | — |
| ~10:34 | 1-5 shovel tutorial | During the tutorial the seed bank slides off-screen, and the shovel click followed it outside the window. | Fixed the shovel position and added bounds checks to every click. |
| 10:36–10:40 | 1-5 bowling | **Won**: 20 decisions. Claude tried to throw nuts past the red line and treated rolling nuts as walls. Reward: Potato Mine. | Rewrote the bowling rules in the prompt. New actions are now blocked once the final reward has been clicked. |
| 10:40–10:46 | 1-6 | **Won**. A pole-vaulter used up the middle-lane mower. | — |
| 10:46–11:01 | 1-7 | **Lost twice.** There were no bugs; the strategy was poor. Rows had no shooters, Peashooters sat in front of Wall-nuts, mowers were lost early and sun went unspent. | The board description now includes a **lane check** that flags `UNDEFENDED` and `DANGER` rows. Added layout and economy tips to the prompt: Sunflowers at the back, shooters in the middle, Wall-nut in front, per-wave targets for shooters per row, and don't hoard sun. |
| 12:07–12:15 | 1-7 | **Won on the first try** after the prompt change. | — |
| 12:15–12:20 | 1-8 | **Won**. | — |
| 12:20–12:28 | 1-9 | **Won**. | — |
| 12:28–12:35 | 1-10 (conveyor) | **Won**. Reward: Puff-shroom. Claude asked five times for a Peashooter that wasn't on the belt, and the validator blocked it each time. | The prompt now says only the cards on the belt exist. |
| ~12:40 | — | Security pass: no API keys, tokens or personal details in the repo or its history. Logs and screenshots stay local. | — |

| Afternoon | — | Speed pass. One decision took about **12 s**, but only about 5 s of that was the model. The rest was Claude Code starting up and loading every MCP connector on the account. | Skipped MCP servers and skills at start-up, which brought a call to about 6 s. Then kept **one Claude process alive** for the whole level, sending each board over stdin. Decisions now take about **2 s** (the first one after a reset about 5 s). The conversation resets each level and every 15 decisions. |
| 13:17–13:23 | 2-1 (night) | **Won** with the fast brain: a median of 1.7 s per decision. It's the first live night level. Reward: Sun-shroom. | — |
| Afternoon | — | 2-1 exposed our own coaching: the hand-written rule "Wall-nut in col 5–6" made Claude wall off Puff-shrooms that only reach 3 tiles. | **Removed all hand-written strategy.** The player now gets the game's rules, plus a one-line card for each plant (the full Almanac stats unlock after 2-4, as they do for a human), and a **journal**. After each level it reads a factual timeline of what happened and rewrites up to 12 lessons in its own words. A test on the old 1-7 loss showed the recorder counted Cherry Bombs as "lost" and Claude thought it controlled the mowers; both were fixed. |
| 14:09–14:39 | 2-2, 2-3 | First levels with a **blank journal** and no coaching. **Won 2-2** (its first journal entry admits the mowers saved it), then **lost 2-3 three times** at wave 10/10. Between attempts its lessons and loadouts changed: it added Sun-shroom, then Sunflower and Fume-shroom, and noted "Puff-shroom has very short range". It still ran out of sun every time. | The plant chooser now handles the game's "no sun producing plants" warning by keeping Claude's choice and telling it afterwards. Requests are now at least 4 s apart, and a board change no longer triggers one when nothing can be planted. |
| 14:45–15:01 | 2-3 | **Method 1, keep retrying:** Haiku with its growing journal lost three more times, six in a row in total. It learned "bring Sunflowers and real damage", but still went broke every time. | — |
| 15:01–15:06 | 2-3 | **Method 2, stronger model:** Sonnet at low effort, starting from a **blank** journal, **won on its first try** with 28 decisions and none wasted. It found the Fume-shroom-and-Potato-Mine middle line by itself. Reward: Grave Buster. | Added `--journal-dir` so each model keeps its own journal. |
| 15:13–15:48 | 2-4 to 2-6 | Sonnet campaign. **2-4: lost, then won** with 7 slots and a "Fume-shrooms behind Wall-nuts in every row" setup it found itself, earning the Almanac. **2-5: Whack-a-Zombie**, played by the script. **2-6: lost twice** to footballs and coneheads, so the run stopped. | Crazy Dave's 7-slot offer is now accepted automatically. The journal skips reflecting on script-played Whack-a-Zombie, after it invented a summary for 2-5. |
| ~16:00 | — | Sonnet knew the right 2-6 setup in its journal, but drifted away from it during play. | No human plan. Instead: **Claude writes its own game plan** before each level (from its journal and the zombie preview) and sees it with every board. Plan, pick and reflection now run at **high effort**, while moves stay at low. The board now shows what a human would see: recharge countdowns, damaged-plant health, Potato Mines arming/armed, sun per minute, and zombie cards (Almanac toughness after 2-4). The journal is split into general lessons plus one section per kind of level. |
| 16:19–16:25 | 2-6 | With its own plan, Sonnet **won 2-6 on its first try** after losing it twice without one. It was close: all 5 mowers were gone by the final wave. It only partly kept to its plan (one Wall-nut instead of one per row), and its reflection noted that wave 10 broke through. Reward: Scaredy-shroom. | — |
| ~16:40 | — | Sonnet kept planting Potato Mines right in front of zombies and leaving mower-less rows thin. | **No new rules:** Claude now *sees the consequences*. "Your mine was eaten 5 s after planting, before it armed" and "row 3's mower fired, no mower now" arrive with its next board. Its post-level timeline shows how long each mine had been planted when it went off, and after a loss which row broke through and when that row's mower had gone. Added `usage_report.py` to count the player's tokens alone. |
| 16:30–17:05 | 2-7 to 2-10 | **Sonnet won all four on its first try**, finishing World 2 (night). Its own plan held up: Sun-shrooms at the back, 2-3 Fume-shrooms per row, Puff-shroom blockers, and Wall-nuts in front. 2-10's conveyor handed it Doom, Ice and Hypno-shrooms, which it saved for clumps and Footballs. | Found that the game's end-of-level mower cash-in was recorded as "all mowers fired", so Claude believed its wins were narrow. Fixed. |
| ~17:30 | — | Token check: 2-7 to 2-10 cost ~2.1M input tokens per level, mostly the long conversation being re-read on every decision. Also repaired Sonnet's journal: its 2-8 to 2-10 reflections were redone without the fake mower cash-in. 2-9 went from "won by the skin of our teeth" to "won with all 5 mowers intact". | Snapshot of both journals committed under `snapshots/`. A new Claude process every 3 decisions instead of 40, a compact board, plant facts sent once per level in the cached prompt, and free seeds no longer trigger requests: about 5–7k input tokens per decision instead of up to ~38k. |
| 18:25–18:58 | 3-1, 3-2 (pool) | First pool levels. **3-1: lost twice**, mostly by ignoring the water rows, then **won** with all 6 mowers after its journal noted "Row 3 (water) was never built up". **3-2: lost twice** when water row 2's Lily Pads were eaten and never rebuilt. Token use fell to ~247k input per attempt, from ~2.1M. | Water planting explained as two actions (pad, then plant); Potato Mines and Spikeweeds rejected on pads. A plan whose moves are all rejected gets a quick retry. |
| 19:01–19:45 | 3-2 to 3-5 | Retried as is (low effort, up to 3 attempts). **3-2 won** on the next try, using its "rebuild the pads" lesson. **3-3: two losses, then a win** with all 6 mowers. **3-4 and 3-5 won first try.** It reached 3-5 without needing medium effort. | Crazy Dave's shop is now detected from the screen and skipped with Next Level. |

On 20 November, Sonnet cleared 3-6 and 3-7 on its first attempt and won 3-8 and 3-9 on retry. It then won 3-10 on its first attempt in 79 gameplay decisions with all six mowers intact.

**Headline numbers:** 1-7 to 1-10 were won back to back in one run. That run took 163 Claude decisions and 214 actions, with **0 failed clicks** and no retries.

**Story beats for the video**
1. Offline-built features hit reality: three controller bugs (a hidden dialog, sun pickup, the shovel off-screen), each found and fixed in minutes.
2. Taking menu clicking away from the AI: a script now handles menus and other screens, so Claude spends its decisions only on plant choices and gameplay.
3. The wall at 1-7: the AI lost twice, and the cause was its strategy, not the code.
4. One change to the AI's view of the board (the lane check) took it from two losses to four wins in a row.
