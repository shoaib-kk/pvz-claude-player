# Development timeline

What changed, when, and why, for use in the video. All times are local, on 19 November 2026.
The player was Claude Haiku at low effort throughout. The exact numbers come from the run logs.

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

**Headline numbers:** 1-7 to 1-10 were won back to back in one run. That run took 163 Claude decisions and 214 actions, with **0 failed clicks** and no retries.

**Story beats for the video**
1. Offline-built features hit reality: three controller bugs (a hidden dialog, sun pickup, the shovel off-screen), each found and fixed in minutes.
2. Taking menu clicking away from the AI: a script now handles menus and other screens, so Claude spends its decisions only on plant choices and gameplay.
3. The wall at 1-7: the AI lost twice, and the cause was its strategy, not the code.
4. One change to the AI's view of the board (the lane check) took it from two losses to four wins in a row.
