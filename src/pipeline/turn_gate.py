"""Hold her reply until the learner has really finished, and undo a turn that
turns out to be a pause.

Work on a turn starts as soon as the learner has been quiet for the short hold
(0.6 s), because the interpreter and renderer need ~1.5 s anyway. Her first
words are only released once the learner has been quiet for commit_after_s
(longer when the words so far look unfinished: "uh", "and", "so", a trailing
comma...). If the learner starts speaking again before that, the turn is
reopened: her reply is cancelled, the state change and history line are rolled
back, and the pieces are merged into one turn.

Once her reply is released, a learner who starts talking is a real barge-in.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from tracing import mark

# Words a sentence rarely ends on. A turn whose last word is one of these is
# probably a pause mid-thought.
UNFINISHED_LAST_WORDS = {
    # fillers
    "um", "uh", "erm", "er", "uhm", "hmm", "mm",
    # a sentence almost never ends on these
    "and", "but", "or", "so", "because", "cause", "if", "when", "while", "since", "although", "though",
    "the", "a", "an", "my", "your", "our", "their",
    "to", "of", "i", "i'm", "we're", "you're", "like", "just", "very",
}
# Deliberately not included, because sentences end on them all the time:
# "go on", "how hard it is", "sorry about that", "what is it for", "come with".


def looks_unfinished(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith((",", "-", "—", "...")):
        return True
    words = re.findall(r"[a-zA-Z']+", stripped.lower())
    return bool(words) and words[-1] in UNFINISHED_LAST_WORDS


@dataclass
class PendingTurn:
    turn_id: int | None = None
    text: str = ""
    fragments: list = field(default_factory=list)
    words: list = field(default_factory=list)
    release_at: float = 0.0
    released: bool = False
    reopened: bool = False
    # How long after the learner stopped the transcript arrived. Large values
    # mean the speech-to-text connection is lagging.
    stt_lag_s: float = 0.0
    # Filled in by the interpreter so the turn can be undone.
    undo: object = None


class TurnGate:
    def __init__(self, commit_after_s: float = 1.0, commit_after_unfinished_s: float = 2.5):
        self.commit_after_s = commit_after_s
        self.commit_after_unfinished_s = commit_after_unfinished_s
        self.learner_stopped_at: float | None = None
        self.pending: PendingTurn | None = None
        # Set by build_session: called with the PendingTurn being undone.
        self.on_reopen = []

    # --- learner side ------------------------------------------------------

    def learner_stopped(self):
        self.learner_stopped_at = time.monotonic()

    def turn_flushed(self, text: str, fragments: list, words: list) -> PendingTurn:
        unfinished = looks_unfinished(text)
        wait = self.commit_after_unfinished_s if unfinished else self.commit_after_s
        now = time.monotonic()
        origin = self.learner_stopped_at or now
        self.pending = PendingTurn(
            text=text, fragments=list(fragments), words=list(words), release_at=origin + wait,
            stt_lag_s=max(0.0, now - origin),
        )
        mark("gate", "holding reply", f"{wait:.1f}s after learner stopped" + (" (sounds unfinished)" if unfinished else ""))
        return self.pending

    def can_reopen(self) -> bool:
        """Only within the pause window. Once it has passed, the turn is
        committed even if her reply is still on its way (a slow network): new
        speech is then a barge-in and a new turn, never merged across a long
        silence."""
        return (
            self.pending is not None
            and not self.pending.released
            and time.monotonic() <= self.pending.release_at
        )

    def reopen(self) -> PendingTurn | None:
        """The learner kept talking before she spoke: undo the turn."""
        if not self.can_reopen():
            return None
        turn = self.pending
        self.pending = None
        turn.reopened = True
        mark("gate", "REOPENED", f"learner kept talking; merging {turn.text!r} into this turn")
        for fn in self.on_reopen:
            fn(turn)
        return turn

    # --- interpreter side --------------------------------------------------

    def attach(self, turn_id: int, undo) -> None:
        if self.pending is not None and self.pending.turn_id is None:
            self.pending.turn_id = turn_id
            self.pending.undo = undo

    # --- renderer side -----------------------------------------------------

    async def wait_release(self, turn_id: int):
        """Sleep until her reply to this turn may be heard. Cancelled (by the
        renderer) if the turn is reopened meanwhile."""
        turn = self.pending
        if turn is None or turn.turn_id != turn_id:
            return
        delay = turn.release_at - time.monotonic()
        if delay > 0:
            mark("gate", "reply ready early", f"waiting {delay:.2f}s more")
            await asyncio.sleep(delay)
        if self.pending is turn:
            turn.released = True
            self.pending = None
