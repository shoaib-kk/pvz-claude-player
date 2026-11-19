# Adventure test results

Live tests use Claude Haiku at low effort on Steam GOTY 1.2.0.1096. Raw logs and screenshots stay local.

## 19 November 2026

| Level | Result | Failure and adjustment |
| --- | --- | --- |
| 1-3, initial continuation | Stopped during navigation | The game reported playing while the saved-game Continue dialog blocked input. Four planting attempts failed. Added detection for that dialog and dismiss it before starting decisions. The saved board had no plants or zombies, so the retry continues from the same point. |
| 1-3, second attempt | Stopped and restarted | Planting worked, but the new pickup filter rejected every live sun pickup because its assumed array-ID tail was zero. The player stayed at zero sun after buying its first Sunflower. Removed that assumption and added a regression using the observed pickup layout. Restarted this affected level. |
| 1-3, third attempt | Won | 16 decisions, 20 action results, zero failed clicks. The game showed the Wall-nut reward. Added local screenshots after each confirmed win or loss so consecutive runs retain visual evidence. |
| Transition to 1-4 | Paused by mouse fail-safe | The cursor reached the bottom-left screen corner during the intro. The bot stopped before planting. Added recovery for ordinary focus-loss pause dialogs during intros and an absolute level endpoint for the continuing test. The corner stop remains an intentional user stop switch. |
| 1-4 | Won | 25 decisions and zero failed clicks. All five mowers remained available at the final wave. Verified the Shovel reward in the saved result screenshot. |
| Transition to 1-5 | Stopped and resumed at tutorial | The seed bank was hidden above the window, and its negative Y position incorrectly moved the calculated shovel click outside the game. Fixed the shovel Y position to the top of the game and added bounds checking to controller clicks. The three tutorial Peashooters were still present when the run stopped. |
| 1-5, planning observations | Validator rejected four illegal launches | Claude proposed columns beyond the red line and described rolling nuts as stationary blockers. The bounds validator rejected the launches. Expanded the bowling description to explain damage, bouncing, and reusable launch cells for future runs. |
| 1-5 | Won | 20 decisions. Verified the Potato Mine reward. One final launch was reported failed shortly before the result transition. Added a waiting period after clicking a final reward, preventing fresh plans from executing during that animation. The bot advanced into 1-6 automatically. |
| 1-6 | Won | Potato Mine used well; a pole-vaulter took the middle-lane mower near the end. |
| 1-7, first and second attempts | Lost (strategy) | No controller faults. Haiku left lanes with no attackers, put Peashooters ahead of Wall-nuts, lost mowers early and sat on unspent sun. Added a per-row "lane check" (attackers, mower, closest zombie, UNDEFENDED/DANGER flags) to the board description and layout/economy rules of thumb to the player prompt. |
| 1-7, third attempt (new run) | Won | First try after the prompt change. |
| 1-8 | Won | |
| 1-9 | Won | |
| 1-10 (conveyor) | Won | Puff-shroom reward verified on screen. Five plans asked for a Peashooter that was not on the belt; the validator rejected them. Added an explicit "only listed cards exist" line for conveyor levels. |
| 2-1 (night), persistent brain | Won | First live run of the long-running Claude process. Decisions took 1.7 s (median), 5.2 s for the first and 7.0 s at most, against about 10 s before. 55 decisions, 31 of 32 actions OK, zero failed clicks. Claude picked Puff-shroom for night by itself. Sun-shroom reward verified on screen. Night mechanics now verified live. |
| 2-2 (night), blank journal, no coaching | Won | First level without hand-written strategy. 93 decisions, 20 of them empty, because a free Puff-shroom is almost always affordable at night and keeps triggering requests. Claude's own summary: it won only because the mowers and Cherry Bombs covered for a weak mushroom line. |
| 2-3, attempt 1 | Lost at wave 10/10 | No sun producer in the loadout. The journal wrote 11 lessons (bring real damage, Puff-shrooms are short range, and others). |
| 2-3, retry | Stalled on the plant chooser | New screen: the game's "You haven't chosen any sun producing plants" warning. The bot now detects it, answers Yes so the player's choice stands, and adds the warning to the journal timeline. Added a test. |
| 2-3, attempts 2 and 3 | Lost at wave 10/10 both times | The loadout changed as the journal grew: Sun-shroom, then Sunflower plus Sun-shroom, and Fume-shroom. Each loss ended with 0 sun and no way to rebuild walls. Haiku at low effort is learning, but not yet enough to win. Stopped here. |

Run of 1-7 to 1-10: 163 decisions, 214 actions, zero failed clicks, no retries needed. 31 offline regression tests pass.

## Repository audit

Re-scanned the 23 publishable files in the working tree on 19 November (after the fixes above) with the same result. Earlier: scanned all three existing commits and their 30 unique file blobs for credential patterns, personal email addresses, and local user paths. The scan found zero matches. Commit emails use the GitHub no-reply address. GitHub reported zero open secret-scanning alerts. Local logs, screenshots, environment files, and the unrelated local audio-review folder are excluded from Git.
