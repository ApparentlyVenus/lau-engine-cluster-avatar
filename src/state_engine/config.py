import json
from dataclasses import dataclass, field

from state_engine.patient_state import DefenseMode, EmotionMode
from state_engine.turn_flags import DEFAULT_BRIEF_DELTAS
from state_engine.validate import TuningValidationError, validate_tuning_file


@dataclass
class Band:
    min: float
    max: float
    description: str


@dataclass
class SeverityScale:
    trust_bands: dict[str, Band]
    saturation_bands: dict[str, Band]


@dataclass
class FlagDelta:
    trust: float
    saturation: float
    acknowledges: bool


@dataclass
class Personality:
    preferred_defense_mode: DefenseMode
    acknowledgment_intensity_threshold: float
    unacknowledged_threshold: int
    trust_penalty: float
    saturation_penalty: float
    defense_trigger_trust: float


@dataclass
class InterruptionConfig:
    trigger_emotions: list[EmotionMode]
    min_intensity: float
    min_seconds_before_interrupt: float
    cooldown_seconds: float
    base_probability: float


@dataclass
class Scenario:
    patient_name: str
    age: int
    prompt: str
    # What the doctor has to tell her. Given to the interpreter (to recognise
    # the disclosure), never to the patient's voice: she does not know it.
    clinical_facts: str = ""


# --- emotional arc ("arc" section, optional) ---------------------------------
#
# Her emotions are scored from trust (T), saturation (S), competence (C) and
# shock each turn; the two strongest become primary and undertone. Each score
# is weight x a product of those, so a weight scales one emotion up or down
# without changing when it appears. f = 1 - shock (how far the shock has faded).
#
#   before the news   CALM = T(1-S)          FEAR = pre_news_anxiety
#                     ANGER = S(1-T)^2       (others 0: she does not know yet)
#   after the news    SHOCK = shock          ANGER = S(1-T)
#                     GRIEF = f*S*T          FEAR = f*S(1-C)
#                     BARGAINING = f*S*(1-2|T-0.55|)   CALM = f*T(1-S)
#   any time          DEFENSIVE = blame (raised by blaming, eased by removing blame)

DEFAULT_WEIGHTS = {"CALM": 1.0, "SHOCK": 1.0, "ANGER": 1.4, "GRIEF": 1.6, "FEAR": 1.3, "BARGAINING": 0.9, "DEFENSIVE": 1.2}

# How strongly each behaviour lands depends on the state she is in when the
# learner says it (the brief's per-state escalation triggers and ways out).
# Keys: her primary emotion, or her active defense. Values multiply the flag's
# trust and saturation change; anything not listed is x1.
DEFAULT_REACTIONS = {
    "SHOCK": {"silence_tolerance": 1.5, "validating": 1.2, "logistics_first": 1.5, "jargon": 1.3},
    "ANGER": {"validating": 1.3, "names_subtext": 1.3, "learner_defensive": 1.5, "premature_reassurance": 1.5},
    "FEAR": {"checks_understanding": 1.8, "jargon": 1.5, "premature_reassurance": 1.2},
    "GRIEF": {"silence_tolerance": 1.3, "logistics_first": 1.3},
    "DEFENSIVE": {"removes_blame": 2.0, "blaming": 1.5, "names_subtext": 1.2},
    "CALM": {"misreads_her": 1.3, "checks_understanding": 1.2},
    "SARCASM": {"names_subtext": 1.8, "misreads_her": 1.6},
    "MINIMIZING": {"names_subtext": 1.3, "premature_reassurance": 1.3},
    "PASSIVE_AGGRESSIVE": {"names_subtext": 1.6, "checks_understanding": 1.3, "misreads_her": 1.5},
}


@dataclass
class ArcConfig:
    # The news itself: added to trust and saturation on the disclosure turn.
    disclosure_trust: float = 0.0
    disclosure_saturation: float = 0.3
    shock_peak: float = 0.9
    # Shock lost per turn after the news...
    shock_decay: float = 0.12
    # ...plus/minus this much per unit of these flags in the turn.
    shock_relief: dict = field(default_factory=lambda: {"validating": 0.12, "silence_tolerance": 0.12})
    shock_prolong: dict = field(default_factory=lambda: {"logistics_first": 0.08, "jargon": 0.06})
    pre_news_anxiety: float = 0.25
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    # Change in competence per unit of each flag (answers_question included).
    competence_deltas: dict = field(default_factory=lambda: {
        "answers_question": 0.06, "validating": 0.02, "checks_understanding": 0.05, "repairs": 0.03,
        "jargon": -0.08, "premature_reassurance": -0.05, "learner_defensive": -0.06,
        "blaming": -0.05, "disrespect": -0.15,
    })
    # Blame: added per unit of "blaming", removed per unit of "removes_blame",
    # and this fraction fades every turn.
    blame_gain: float = 0.6
    blame_relief: float = 0.5
    blame_decay: float = 0.25
    # Frustration: once this many of her questions in a row go unanswered,
    # every further one costs this much trust and adds this much saturation.
    frustration_after: int = 2
    frustration_trust: float = -0.04
    frustration_saturation: float = 0.06
    # She ends the consultation after this many turns in a row with trust at
    # or below walkout_trust. 0 turns disables it.
    walkout_trust: float = 0.05
    walkout_turns: int = 2


# --- how she speaks per emotion ("speech" section, optional) -----------------

@dataclass
class SpeechProfile:
    # Extra wait before her reply starts, at full intensity (scaled by it).
    reply_delay_s: float = 0.0
    # ElevenLabs voice speed (Flash/Turbo only; v3 has no speed control).
    speed: float = 1.0
    # ElevenLabs stability; lower is more expressive. None keeps the voice's.
    stability: float | None = None
    # How her speech sounds; given to the renderer.
    style: str = ""


DEFAULT_SPEECH = {
    "CALM": SpeechProfile(0.0, 1.0, None, "Even and clear: complete sentences at a normal pace, few fillers."),
    "SHOCK": SpeechProfile(1.2, 0.85, 0.35, "Halting and slow: short fragments, trailing off, may repeat a word (\"Cancer. Cancer.\"), fillers like \"Oh...\" or \"I...\", long silences ([pause] if allowed)."),
    "ANGER": SpeechProfile(0.0, 1.1, 0.3, "Fluent and clipped: short, direct sentences, no fillers, no hesitation; may challenge the doctor directly."),
    "FEAR": SpeechProfile(0.2, 1.08, 0.35, "Quick and uneven: repeats the same question (\"What does this mean, what does this actually mean?\"), restarts sentences, fillers like \"uh\"."),
    "GRIEF": SpeechProfile(1.0, 0.85, 0.45, "Slow and quiet: very few words, trailing off, long pauses, flat tone."),
    "BARGAINING": SpeechProfile(0.3, 1.0, 0.4, "Searching: hopeful or pleading questions looking for another possibility."),
    "DEFENSIVE": SpeechProfile(0.0, 1.05, 0.35, "Firm and justifying: lists what they did right (\"I don't smoke, I exercise, I never miss a check-up\"), short and a little rigid."),
}


# Used when a character file has no severity_scale. The renderer reads these
# descriptions, so they say "the patient", whoever the patient is.
DEFAULT_SEVERITY_SCALE = {
    "trust_bands": {
        "trusting": {"min": 0.70, "max": 1.00, "description": "The patient trusts the learner and is willing to engage openly."},
        "guarded": {"min": 0.45, "max": 0.69, "description": "The patient answers but holds back, waiting to see if the learner earns more trust."},
        "distrustful": {"min": 0.20, "max": 0.44, "description": "The patient questions what they are told and may lean sarcastic or defensive."},
        "shut_down": {"min": 0.00, "max": 0.19, "description": "The patient has largely disengaged; responses are short and closed off."},
    },
    "saturation_bands": {
        "calm": {"min": 0.00, "max": 0.29, "description": "The patient can take in more without becoming overwhelmed."},
        "strained": {"min": 0.30, "max": 0.59, "description": "The patient is processing a lot and needs pacing, not more information."},
        "overwhelmed": {"min": 0.60, "max": 0.84, "description": "The patient is close to an emotional peak."},
        "breaking_point": {"min": 0.85, "max": 1.00, "description": "The patient is at their limit; any further pressure risks a sharp reaction."},
    },
}


@dataclass
class PersonaConfig:
    scenario: Scenario
    severity_scale: SeverityScale
    audio_tags: dict[EmotionMode, list[str]]
    personality: Personality
    flag_deltas: dict[str, FlagDelta]
    interruption: InterruptionConfig
    raw_initial_state: dict
    arc: ArcConfig = field(default_factory=ArcConfig)
    speech: dict = field(default_factory=dict)  # EmotionMode -> SpeechProfile
    # State name (emotion or defense) -> {flag: multiplier}; see DEFAULT_REACTIONS.
    reactions: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_REACTIONS.items()})

    def reaction(self, state_name: str, flag: str) -> float:
        return self.reactions.get(state_name, {}).get(flag, 1.0)

    def speech_for(self, emotion: EmotionMode) -> SpeechProfile:
        return self.speech.get(emotion) or DEFAULT_SPEECH.get(emotion.name) or SpeechProfile()

    @classmethod
    def from_file(cls, path: str) -> "PersonaConfig":
        try:
            validate_tuning_file(path)
        except TuningValidationError as e:
            raise ValueError(f"Cannot load persona, tuning file is invalid:\n{e}")

        with open(path, "r") as f:
            raw = json.load(f)
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> "PersonaConfig":
        scale = raw.get("severity_scale") or DEFAULT_SEVERITY_SCALE
        severity_scale = SeverityScale(
            trust_bands={k: Band(**v) for k, v in scale["trust_bands"].items()},
            saturation_bands={k: Band(**v) for k, v in scale["saturation_bands"].items()},
        )

        audio_tags = {
            EmotionMode[name]: tags for name, tags in raw["audio_tags"].items()
        }

        p = raw["personality"]
        personality = Personality(
            preferred_defense_mode=DefenseMode[p["preferred_defense_mode"]],
            acknowledgment_intensity_threshold=p["acknowledgment_intensity_threshold"],
            unacknowledged_threshold=p["unacknowledged_threshold"],
            trust_penalty=p["trust_penalty"],
            saturation_penalty=p["saturation_penalty"],
            defense_trigger_trust=p["defense_trigger_trust"],
        )

        # The brief's extra behaviours are optional in a file: defaults first.
        flag_deltas = {
            name: FlagDelta(trust=t, saturation=sat, acknowledges=ack)
            for name, (t, sat, ack) in DEFAULT_BRIEF_DELTAS.items()
        }
        flag_deltas.update({
            name: FlagDelta(trust=v["trust"], saturation=v["saturation"], acknowledges=v["acknowledges"])
            for name, v in raw["flag_deltas"].items()
        })

        i = raw["interruption"]
        interruption = InterruptionConfig(
            trigger_emotions=[EmotionMode[name] for name in i["trigger_emotions"]],
            min_intensity=i["min_intensity"],
            min_seconds_before_interrupt=i["min_seconds_before_interrupt"],
            cooldown_seconds=i["cooldown_seconds"],
            base_probability=i["base_probability"],
        )

        s = raw["scenario"]
        scenario = Scenario(
            patient_name=s["patient_name"],
            age=s["age"],
            prompt=s["prompt"],
            clinical_facts=s.get("clinical_facts", ""),
        )

        a = dict(raw.get("arc") or {})
        disclosure = a.pop("disclosure", {})
        dict_keys = ("weights", "shock_relief", "shock_prolong", "competence_deltas")
        arc = ArcConfig(**{k: v for k, v in a.items() if k not in dict_keys})
        # A partial dict in the file overrides only the keys it names.
        for k in dict_keys:
            setattr(arc, k, {**getattr(arc, k), **(a.get(k) or {})})
        arc.disclosure_trust = disclosure.get("trust", arc.disclosure_trust)
        arc.disclosure_saturation = disclosure.get("saturation", arc.disclosure_saturation)

        reactions = {k: dict(v) for k, v in DEFAULT_REACTIONS.items()}
        for name, mults in (raw.get("reactions") or {}).items():
            reactions[name] = {**reactions.get(name, {}), **mults}

        speech = {}
        for name, prof in (raw.get("speech") or {}).items():
            base = DEFAULT_SPEECH.get(name, SpeechProfile())
            speech[EmotionMode[name]] = SpeechProfile(**{**base.__dict__, **prof})

        return cls(
            scenario=scenario,
            severity_scale=severity_scale,
            audio_tags=audio_tags,
            personality=personality,
            flag_deltas=flag_deltas,
            interruption=interruption,
            raw_initial_state=raw["initial_state"],
            arc=arc,
            speech=speech,
            reactions=reactions,
        )

    def trust_band(self, value: float) -> Band:
        candidates = sorted(self.severity_scale.trust_bands.values(), key=lambda b: b.min, reverse=True)
        for band in candidates:
            if value >= band.min:
                return band
        raise ValueError(f"trust value {value} is below every configured band")

    def saturation_band(self, value: float) -> Band:
        candidates = sorted(self.severity_scale.saturation_bands.values(), key=lambda b: b.min, reverse=True)
        for band in candidates:
            if value >= band.min:
                return band
        raise ValueError(f"saturation value {value} is below every configured band")

    def allowed_tags(self, emotion: EmotionMode) -> list[str]:
        return self.audio_tags.get(emotion, [])

def tuning_defaults() -> dict:
    """The optional sections' defaults, shaped like the tuning file (for the
    editor's placeholders)."""
    arc = ArcConfig()
    a = {k: v for k, v in arc.__dict__.items() if not k.startswith("disclosure_")}
    a["disclosure"] = {"trust": arc.disclosure_trust, "saturation": arc.disclosure_saturation}
    return {
        "arc": a,
        "speech": {name: dict(p.__dict__) for name, p in DEFAULT_SPEECH.items()},
        "initial_state": {"competence": 0.6},
        "severity_scale": DEFAULT_SEVERITY_SCALE,
        "avatar": {"url": "/static/avatar/patient.glb", "body": "F"},
        "reactions": DEFAULT_REACTIONS,
        "flag_deltas": {
            name: {"trust": t, "saturation": sat, "acknowledges": ack}
            for name, (t, sat, ack) in DEFAULT_BRIEF_DELTAS.items()
        },
    }


def build_scenario_block(persona) -> str:
    return f"""Patient: {persona.scenario.patient_name}, age {persona.scenario.age}
{persona.scenario.prompt}"""