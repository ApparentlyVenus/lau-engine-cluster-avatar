import json
from dataclasses import dataclass

from state_engine.patient_state import EmotionMode, DefenseMode
from state_engine.validate import validate_tuning_file, TuningValidationError


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


@dataclass
class PersonaConfig:
    scenario: Scenario
    severity_scale: SeverityScale
    audio_tags: dict[EmotionMode, list[str]]
    personality: Personality
    flag_deltas: dict[str, FlagDelta]
    interruption: InterruptionConfig
    raw_initial_state: dict

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
        )

        return cls(
            scenario=scenario,
            severity_scale=severity_scale,
            audio_tags=audio_tags,
            personality=personality,
            flag_deltas=flag_deltas,
            interruption=interruption,
            raw_initial_state=raw["initial_state"],
        )

    def trust_band(self, value: float) -> Band:
        for band in self.severity_scale.trust_bands.values():
            if band.min <= value <= band.max:
                return band
        raise ValueError(f"trust value {value} does not fall within any configured band")

    def saturation_band(self, value: float) -> Band:
        for band in self.severity_scale.saturation_bands.values():
            if band.min <= value <= band.max:
                return band
        raise ValueError(f"saturation value {value} does not fall within any configured band")

    def allowed_tags(self, emotion: EmotionMode) -> list[str]:
        return self.audio_tags.get(emotion, [])

def build_scenario_block(persona) -> str:
    return f"""Patient: {persona.scenario.patient_name}, age {persona.scenario.age}
{persona.scenario.prompt}"""