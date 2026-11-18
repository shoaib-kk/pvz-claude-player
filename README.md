# PvZ Claude Player

Claude plays Adventure levels in Plants vs. Zombies GOTY. A Windows Python script reads the local game board, asks Claude for a short build plan, and turns that plan into mouse clicks. The project supports the Steam build **1.2.0.1096** in an **800 × 600 window**.

## Quick start

1. Install Plants vs. Zombies GOTY through Steam and turn off **Full Screen** in the game's options.
2. Install Python 3.12 and, for subscription mode, [Claude Code](https://code.claude.com/docs/en/setup). Run these commands from the repository folder in PowerShell.

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   claude auth login
   ```

3. Open Adventure or leave the game on its level reward screen. Keep the game window visible in your Windows desktop session.
4. Start the player with Haiku at low effort.

   ```powershell
   $env:PVZ_MODEL = 'haiku'
   $env:PVZ_EFFORT = 'low'
   .\.venv\Scripts\python.exe agent.py
   ```

The script controls the real mouse cursor and stops after one level. Leave the mouse and keyboard idle while it plays. To interrupt, press **Ctrl+C** in its terminal or move the cursor into a screen corner. If the reader cannot attach to the game, try running the terminal as administrator.

## How it works

1. [`state.py`](state.py) reads the local game process using the build-specific offsets in [`offsets.py`](offsets.py). It reads the lawn, sun, seed bank, plants, zombies, mowers, pickups, and current scene.
2. [`brains.py`](brains.py) turns the latest board into text. Claude returns an ordered JSON plan of up to five placements or shovel actions. On levels with a plant chooser, Claude also picks the loadout from the available cards. Any slots locked by Crazy Dave are kept.
3. [`agent.py`](agent.py) asks Claude in a background thread while the game keeps running. It requests a new plan when the current one is exhausted and a seed is affordable, when a threat changes, or after roughly 30 seconds if a seed is affordable. A fresh answer replaces the unfinished plan.
4. [`controller.py`](controller.py) executes the validated actions with mouse clicks. Actions can wait for sun or recharge. Invalid actions are skipped and reported back to Claude. Sun and money collection and reward clicks are scripted.

Rows and columns are zero-indexed. Row 0 is the top lane, and column 0 is closest to the house.

## Run modes

| Command or launcher | What it does |
| --- | --- |
| `agent.py` or `5 - AI plays (continue current level).bat` | Continue from the current Adventure screen with your Claude Code login. |
| `agent.py --restart` or launcher 4 | Restart the current level and discard its in-progress board. |
| `agent.py --brain simple` or launcher 8 | Play with local rules and zero Claude calls. Use this to check clicks and game-state reading. |
| `agent.py --brain claude` or launcher 6 | Use the Anthropic API with `ANTHROPIC_API_KEY`. API usage is billed separately. |
| `agent.py --max-decisions 5` | End the run after five in-level decisions. A plant-picker call can also occur before play. |
| `brain_check.py subscription` | Ask Claude for one decision on the live board without clicking. |
| `state.py --once` | Read the current game state without calling Claude. |

Run Python commands with `.\.venv\Scripts\python.exe` from the repository folder. Launcher 9 sets Haiku and low effort before starting subscription mode. To change the model or reasoning effort, set `PVZ_MODEL` and `PVZ_EFFORT` before launching.

## Logs and recording

Each run writes a local JSONL log under `logs/`. It records board snapshots, prompts, plans, timings, usage when reported, action outcomes, and the level result. Check the game screen alongside the log to verify a win.

To show Claude's reasoning and plan in OBS, add a **Text (GDI+)** source, select **Read from file**, and point it to the generated `overlay.txt`.

## Reducing Claude usage

- **Start with fewer calls.** The script already queues several moves per answer. A useful next experiment is to preserve a valid queue through routine changes and replan early when a mower is spent or a dangerous zombie approaches the house. This keeps the response to urgent events fast.
- **Send a smaller board.** Keep lane threat, mower, seed cost and recharge, and enough cell coordinates to pick a legal move. Encode repeated plant names once and report only recent failures that affect the next plan.
- **Keep decision output short.** Use Haiku at low effort for tests. Try one short reasoning sentence for the OBS overlay. Run the local rules player for calibration, game reading, and click tests.
- **Compare completed runs.** Record calls per level, input tokens by cache bucket, output and thinking tokens, and whether the level was won. Compare the same level, loadout, and model settings where possible. Claude's token breakdown is useful for comparisons, while Claude Code subscription limits are managed separately. [Anthropic's usage field reference](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#understanding-the-token-breakdown)

## Supported levels

Normal daytime front-lawn Adventure levels, including early tutorial boards with bare dirt, are the current target. Conveyor levels and bowling, night and grave mechanics, pool and fog, roof, and Dr. Zomboss are outside the supported set.
