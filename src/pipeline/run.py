"""Kept for old commands. Everything now runs through src/run.py:

    python src/run.py web     (browser mic, works in the devcontainer)
    python src/run.py mic     (local PyAudio mic, on your own machine)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run import main  # noqa: E402

if __name__ == "__main__":
    # old form: python pipeline/run.py tuning.json  -> local mic
    args = sys.argv[1:]
    if args and args[0].endswith(".json"):
        main(["mic", "--persona", args[0], *args[1:]])
    else:
        main(args)
