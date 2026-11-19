"""What the patient says when the model breaks character.

The renderer occasionally answers as the model instead of as the patient
("I'm not able to continue this roleplay", "As an AI..."), usually after
abusive or strange input. That must never reach the learner's ears, so the
reply is replaced by an in-character fallback line.

One fixed line ("I'm not doing this...") sounded scripted once it happened
more than once in a session, and it read as the patient walking out even when
the conversation was calm. The lines here fit the moment instead:

  * before the news: polite confusion, nothing that assumes a diagnosis;
  * after the news: a line for the patient's current emotion;
  * trust near zero: the firm "I want someone else" line;

and a session does not repeat a line until every other line for that moment
has been used. Nothing here imports Pipecat, so it is easy to test.
"""

import random
import re

_OUT_OF_CHARACTER = re.compile(
    r"\b(role-?play|role play|simulation|the learner|as an ai|language model|i'?m an ai|anthropic|"
    r"i can'?t (engage|continue|help with)|i'?m not able to continue|i won'?t continue|"
    r"training exercise|in character|out of character|break(ing)? character|step out of (this|the) (role|scenario))\b",
    re.IGNORECASE,
)


def is_out_of_character(text: str) -> bool:
    return bool(_OUT_OF_CHARACTER.search(text))


# Kept for anything that still imports it: the line used when trust is gone.
OUT_OF_CHARACTER_FALLBACK = "I'm not doing this. I want to speak to someone else, please."

LOW_TRUST = 0.2

FALLBACK_LINES: dict[str, list[str]] = {
    # Before the news: she does not know anything yet.
    "BEFORE_NEWS": [
        "Sorry, could you say that again?",
        "I'm sorry, I'm a bit nervous. What were you saying?",
        "Sorry, I didn't follow. Could you repeat that?",
        "Sorry. Can we just get to the results?",
    ],
    "SHUT_DOWN": [
        OUT_OF_CHARACTER_FALLBACK,
        "[firmly] I don't want to talk about this with you anymore.",
        "No. I'm done. Can someone else come in, please?",
    ],
    "CALM": [
        "Sorry, could you say that again?",
        "I'm sorry, I lost you there. What were you saying?",
        "Sorry, can you explain that a different way?",
    ],
    "SHOCK": [
        "[quietly] I... sorry. I need a second.",
        "I can't think straight right now. Can you give me a moment?",
        "[hesitant] Sorry... what did you say?",
    ],
    "ANGER": [
        "[sharp tone] No. I'm not answering that.",
        "Just tell me what's going on. Plainly.",
        "[firmly] I don't see what that has to do with anything.",
    ],
    "GRIEF": [
        "[quietly] I can't... give me a moment.",
        "I'm sorry. I just need a minute.",
        "[sighs] I don't know what to say.",
    ],
    "FEAR": [
        "I don't understand. What happens now?",
        "Sorry, can you go back? I think I missed something.",
        "[hesitant] I'm sorry, I'm scared. Can you say that again?",
    ],
    "BARGAINING": [
        "Isn't there anything else we could try?",
        "Sorry, I just keep thinking there must be another way.",
        "Can we go over the options again?",
    ],
    "DEFENSIVE": [
        "I don't see why that matters.",
        "[firmly] I did everything I was supposed to do.",
        "Can we just talk about what happens next?",
    ],
}


def fallback_key(state) -> str:
    """Which set of lines fits the patient's state (None: before anything)."""
    if state is None:
        return "BEFORE_NEWS"
    if getattr(state, "trust", 1.0) <= LOW_TRUST:
        return "SHUT_DOWN"
    if not getattr(state, "news_delivered", False):
        return "BEFORE_NEWS"
    emotion = getattr(getattr(getattr(state, "emotion", None), "primary", None), "name", "CALM")
    return emotion if emotion in FALLBACK_LINES else "CALM"


class FallbackLines:
    """Picks fallback lines for one session, without repeats."""

    def __init__(self, lines: dict[str, list[str]] | None = None, rng: random.Random | None = None):
        self.lines = lines or FALLBACK_LINES
        self.rng = rng or random.Random()
        self.used: dict[str, set[str]] = {}
        self.count = 0  # times the model broke character this session

    def pick(self, state) -> str:
        key = fallback_key(state)
        pool = self.lines.get(key) or self.lines["CALM"]
        used = self.used.setdefault(key, set())
        fresh = [line for line in pool if line not in used]
        if not fresh:  # every line used once: start again
            used.clear()
            fresh = list(pool)
        line = self.rng.choice(fresh)
        used.add(line)
        self.count += 1
        return line
