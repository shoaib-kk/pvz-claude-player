"""One decision from a brain on the current board, no clicks. Usage:
    python brain_check.py [subscription|claude|simple]
"""
import json
import sys
import time

from brains import make_brain
from state import GameReader

brain = make_brain(sys.argv[1] if len(sys.argv) > 1 else "subscription")
state = GameReader().snapshot()
if not state.get("in_level"):
    sys.exit("Start a level first.")
t = time.time()
decision = brain.decide(state, [])
prompt = decision.pop("_prompt", "")
print(prompt)
print("\n--- decision after", round(time.time() - t, 1), "s ---")
print(json.dumps(decision, indent=2))
