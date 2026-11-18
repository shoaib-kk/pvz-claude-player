# PvZ Claude Player

Claude plays Plants vs. Zombies GOTY on Windows. It reads a text snapshot of the lawn and decides what to plant or shovel. A Python controller turns those decisions into clicks in the running game.

## How it works

1. **Read the lawn.** [`state.py`](state.py) reads the game process using build-specific offsets from [`offsets.py`](offsets.py). The snapshot includes sun, seed costs and recharge status, plant positions, zombies, lawn mowers, and the current wave. [`brains.py`](brains.py) turns that snapshot into text, with a grid Claude can use to choose cells.
2. **Ask Claude for a plan.** Claude returns up to five ordered actions as JSON. The game keeps running while Claude thinks in a background thread. The planner is called when its queue runs out and something is affordable, when a threat changes, or after about 30 seconds if something is affordable.
3. **Check and execute each move.** [`agent.py`](agent.py) checks queued actions against the live board. If Claude queues a Peashooter at 75 sun, for example, it waits until there is 100 sun and the seed has recharged. If the cell is occupied when the move comes up, the script can skip it and report why in the next prompt. [`controller.py`](controller.py) clicks the seed packet and the target cell.
4. **Handle the rest of the level.** The script collects sun and coins between decisions. On the chooser screen, [`seed_select.py`](seed_select.py) reads the available cards, keeps any plants locked in by Crazy Dave, and clicks the slots Claude picks. The agent detects a win or loss, collects the final reward after a win, and stops after one level.

## What a run records

The local JSONL log records each board snapshot sent to Claude, its plan, which actions went through, and the level result. It also captures response times and token usage when available. The recording overlay shows Claude’s latest explanation and planned moves.

## Current scope

The player targets normal daytime front-lawn levels on the Steam GOTY build **1.2.0.1096**, including early Adventure tutorials. Full Adventure support would also require conveyor levels, night and graves, pool and fog, roof, and the Dr. Zomboss fight.
