from dataclasses import dataclass

# Behaviours every character file must give trust/saturation deltas for.
CORE_FLAGS = (
    "validating",
    "premature_reassurance",
    "jargon",
    "logistics_first",
    "silence_tolerance",
    "interruption",
    "disrespect",
)

# Behaviours named in the clinical brief. Optional in a character file: these
# defaults apply unless the file sets its own (state_engine.config).
BRIEF_FLAGS = (
    "names_subtext",         # names the feeling under her sarcasm, anger or "it's fine"
    "removes_blame",         # tells her this is not something she caused
    "checks_understanding",  # small chunks, checks what she took in, invites questions
    "repairs",               # owns a misstep of their own and corrects course
    "blaming",               # implies she caused or should have caught it
    "learner_defensive",     # argues back, justifies themselves, cites protocol when challenged
    "misreads_her",          # takes sarcasm literally, forced cheer, or treats her calm as fine and skips checking in
)

BEHAVIOUR_FLAGS = CORE_FLAGS + BRIEF_FLAGS

# trust, saturation, acknowledges (resets the "ignored" counter)
DEFAULT_BRIEF_DELTAS = {
    "names_subtext": (0.10, -0.08, True),
    "removes_blame": (0.06, -0.05, True),
    "checks_understanding": (0.04, -0.05, False),
    "repairs": (0.08, -0.04, True),
    "blaming": (-0.10, 0.12, False),
    "learner_defensive": (-0.08, 0.10, False),
    "misreads_her": (-0.06, 0.06, False),
}


@dataclass
class TurnFlags:
    validating: float = 0.0
    premature_reassurance: float = 0.0
    jargon: float = 0.0
    logistics_first: float = 0.0
    silence_tolerance: float = 0.0
    interruption: float = 0.0
    disrespect: float = 0.0
    names_subtext: float = 0.0
    removes_blame: float = 0.0
    checks_understanding: float = 0.0
    repairs: float = 0.0
    blaming: float = 0.0
    learner_defensive: float = 0.0
    misreads_her: float = 0.0
    # Not behaviours: events the interpreter also reports.
    answers_question: float = 0.0
    discloses_news: float = 0.0

    def behaviours(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in BEHAVIOUR_FLAGS}
