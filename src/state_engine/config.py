import json
from dataclasses import dataclass, field

from state_engine.patient_state import DefenseMode, EmotionMode
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

DEFAULT_WEIGHTS = {"CALM": 1.0, "SHOCK": 1.0, "ANGER": 1.4, "GRIEF": 1.6, "FEAR": 1.3, "BARGAINING": 0.9}


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
        "answers_question": 0.06, "validating": 0.02, "jargon": -0.08,
        "premature_reassurance": -0.05, "disrespect": -0.15,
    })
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
    "FEAR": SpeechProfile(0.2, 1.08, 0.35, "Quick and uneven: repeats her question (\"What does this mean, what does this actually mean?\"), restarts sentences, fillers like \"uh\"."),
    "GRIEF": SpeechProfile(1.0, 0.85, 0.45, "Slow and quiet: very few words, trailing off, long pauses, flat tone."),
    "BARGAINING": SpeechProfile(0.3, 1.0, 0.4, "Searching: hopeful or pleading questions looking for another possibility."),
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
        scale = raw["severity_scale"]
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

        flag_deltas = {
            name: FlagDelta(trust=v["trust"], saturation=v["saturation"], acknowledges=v["acknowledges"])
            for name, v in raw["flag_deltas"].items()
        }

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
    }


def build_scenario_block(persona) -> str:
    return f"""Patient: {persona.scenario.patient_name}, age {persona.scenario.age}
{persona.scenario.prompt}"""