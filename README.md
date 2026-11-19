# PvZ Claude Player

Claude plays Plants vs. Zombies GOTY on Windows. It reads a text snapshot of the lawn and decides what to plant or shovel. A Python controller turns those decisions into clicks in the running game.

## How it works

1. **Read the lawn.** [`state.py`](state.py) reads the game process using build-specific offsets from [`offsets.py`](offsets.py). The snapshot includes sun, seed costs and recharge status, plant positions, zombies, lawn mowers, and the current wave. [`brains.py`](brains.py) turns that snapshot into text, with a grid Claude can use to choose cells.
2. **Ask Claude for a plan.** Claude returns up to five ordered actions as JSON. The game keeps running while Claude thinks in a background thread. The planner is called when its queue runs out and something is affordable, when a threat changes, or after about 30 seconds if something is affordable.
3. **Check and execute each move.** [`agent.py`](agent.py) checks queued actions against the live board. If Claude queues a Peashooter at 75 sun, for example, it waits until there is 100 sun and the seed has recharged. It checks graves, craters, aquatic plants, Lily Pads, Flower Pots, sleeping mushrooms, and upgrades. [`controller.py`](controller.py) uses terrain-specific click positions for five-row lawns, six-row pool boards, and the roof slope.
4. **Handle special levels.** Conveyor cards are free, single-use plants whose click positions move across the bank. Wall-nut Bowling limits launches to the first three columns. Vasebreaker exposes temporary seed packets and adds a vase-breaking action to Claude's plans. Scripted reflexes click zombies in Whack-a-Zombie and counter Zomboss fire and ice balls with the matching instant plant. Sun and coin collection are also scripted.
5. **Advance through Adventure.** A level ends after the game changes to a confirmed result screen. Consecutive-level mode navigates the title screen, rewards, Crazy Dave dialogue, plant selection, and the intervening Almanac, shop, shovel tutorial, and Zen Garden tutorial. It clears the old plan between boards and checks the next Adventure level number. It can retry losses up to a specified count and finishes at 5-10.

The default run ends after one level. Consecutive play is enabled with `--levels N`, `--campaign`, or an absolute endpoint such as `--until-level 10`. The `--retries N` option controls loss retries. The included `10 - AI plays consecutive levels.bat` chooses Haiku at low effort and allows two retries per level. Navigation has a timeout, and repeated player or board-reading errors stop the run.

Menus and transitions use a deterministic bot and consume zero Claude decisions. It handles saved-game Continue dialogs and focus-loss pauses during intros. Claude is called for the loadout and board plans. Each confirmed result gets a local screenshot, allowing wins and failures to be reviewed after automatic transitions. [Live test results](TEST_RESULTS.md)

## What a run records

The local JSONL log records each board snapshot sent to Claude, its plan, which actions went through, and the level result. It also captures response times and token usage when available. The recording overlay shows Claude’s latest explanation and planned moves.

The agent skips periodic Claude calls when the wave, threats, plants, and affordable cards are unchanged. It sends a compact board and starts a fresh Claude Code conversation after three decisions by default. The player's level plan and journal carry forward across those resets. [Player usage report](usage_report.py)

## Implementation and verification

Daytime front-lawn play has been verified on the Steam GOTY build **1.2.0.1096**. The broader Adventure mechanics and transitions are implemented from public game references and covered by offline regression tests using synthetic memory and mocked input. Full-campaign play, the added memory fields, and the new screen navigation still need live verification on the target build.

The extension targets Adventure, including its special levels. Standalone puzzle, Survival, and other challenge menus have separate progression rules.

The reference code describes the original game layouts and mechanics. GOTY-specific fields have differences, so inferred offsets require extra care during future live checks. The project reads game memory and sends mouse input. [Public PvZ reference](https://github.com/Patoke/re-plants-vs-zombies/tree/main/Lawn)
