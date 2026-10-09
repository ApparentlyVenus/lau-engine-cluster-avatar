"""Learner timing: measured in code, handed to Claude as text.

Two sources:
1. Word timestamps from Riva (per word start/end, in ms from the start of the
   audio stream). These give pauses inside a turn, speaking rate and fillers.
2. Wall-clock events in the pipeline (her audio starting and stopping, the
   learner's voice starting). These give the gap after her line and whether the
   learner talked over her.

Nothing here calls a model. Claude never does arithmetic on timestamps; it gets
a short annotated version of the turn and decides what the pauses mean.

Thresholds live in an optional "timing" section of the tuning file so the
clinical team can change them without touching code.
"""

import json
from dataclasses import dataclass, field, fields

FILLERS = {"um", "uh", "erm", "er", "uhm", "hmm", "mm", "ah", "eh"}


@dataclass
class TimingConfig:
    # A gap between words at least this long is shown as [pause Ns].
    pause_threshold_s: float = 0.7
    # Speaking rate bands, words per minute.
    slow_wpm: float = 100.0
    fast_wpm: float = 180.0
    # Ignore rate for very short turns; a 3-word turn has no meaningful rate.
    min_words_for_rate: int = 6
    # Learner voice starting while her audio plays counts as talking over her
    # only once she has been audible this long. If she started inside the
    # learner's own pause and they carried on, that is on her, not them.
    talk_over_min_bot_speaking_s: float = 1.0
    # Strength of the measured interruption flag.
    talk_over_flag: float = 1.0

    @classmethod
    def from_tuning_file(cls, path: str) -> "TimingConfig":
        with open(path) as f:
            raw = json.load(f).get("timing", {})
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown keys in tuning 'timing' section: {sorted(unknown)}")
        return cls(**raw)


@dataclass
class Word:
    word: str
    start_s: float
    end_s: float


def words_from_riva_result(result) -> list[Word]:
    """Pull word timings out of a Riva StreamingRecognitionResult.

    Returns [] when the result has none (word_time_offsets off, or the hosted
    model does not fill them in).
    """
    try:
        alternatives = result.alternatives
        if not alternatives:
            return []
        return [
            Word(w.word, w.start_time / 1000.0, w.end_time / 1000.0)
            for w in alternatives[0].words
            if w.word
        ]
    except AttributeError:
        return []


@dataclass
class LiveTiming:
    """Measured from pipeline events, not from Riva."""
    gap_after_her_line_s: float | None = None  # None: she has not spoken yet, or no audio
    talked_over_her: bool = False


@dataclass
class TurnTiming:
    words: list[Word] = field(default_factory=list)
    live: LiveTiming = field(default_factory=LiveTiming)

    def pauses(self, cfg: TimingConfig) -> list[tuple[int, float]]:
        """(index of the word the pause comes after, length in seconds)."""
        out = []
        for i in range(len(self.words) - 1):
            gap = self.words[i + 1].start_s - self.words[i].end_s
            # Riva offsets restart if the stream reconnects; a negative or huge
            # gap is not a real pause.
            if cfg.pause_threshold_s <= gap < 30.0:
                out.append((i, gap))
        return out

    def speaking_rate_wpm(self, cfg: TimingConfig) -> float | None:
        spoken = [w for w in self.words if w.word.lower().strip(".,?!") not in FILLERS]
        if len(spoken) < cfg.min_words_for_rate:
            return None
        duration = self.words[-1].end_s - self.words[0].start_s
        # Exclude long pauses so a thoughtful pause does not read as slow speech.
        duration -= sum(gap for _, gap in self.pauses(cfg))
        if duration <= 0:
            return None
        return len(spoken) / duration * 60.0

    def filler_count(self) -> int:
        return sum(1 for w in self.words if w.word.lower().strip(".,?!") in FILLERS)


def annotate_transcript(transcript: str, timing: TurnTiming, cfg: TimingConfig) -> str:
    """The learner's turn with [pause Ns] markers between words.

    Falls back to the plain transcript when there are no word timings. The text
    comes from Riva's word list rather than the transcript string, because the
    transcript has punctuation re-added and does not line up word for word.
    """
    if not timing.words:
        return transcript
    pause_after = dict(timing.pauses(cfg))
    parts = []
    for i, w in enumerate(timing.words):
        parts.append(w.word)
        if i in pause_after:
            parts.append(f"[pause {pause_after[i]:.1f}s]")
    return " ".join(parts)


def timing_block(timing: TurnTiming, cfg: TimingConfig) -> str | None:
    """A few measured facts, or None when nothing was measured."""
    lines = []
    live = timing.live
    if live.talked_over_her:
        lines.append("Started speaking while she was still talking.")
    elif live.gap_after_her_line_s is not None:
        lines.append(f"Started speaking {live.gap_after_her_line_s:.1f}s after she finished.")

    if timing.words:
        pauses = timing.pauses(cfg)
        if pauses:
            i, longest = max(pauses, key=lambda p: p[1])
            lines.append(f"Longest pause: {longest:.1f}s, after \"{timing.words[i].word}\".")
        else:
            lines.append("No pauses inside the turn.")
        rate = timing.speaking_rate_wpm(cfg)
        if rate is not None:
            band = "slow" if rate < cfg.slow_wpm else "fast" if rate > cfg.fast_wpm else "normal"
            lines.append(f"Speaking rate: {rate:.0f} words/min ({band}).")
        fillers = timing.filler_count()
        if fillers:
            lines.append(f"Filler words (um, uh): {fillers}.")

    if not lines:
        return None
    return "\n".join(f"- {line}" for line in lines)
