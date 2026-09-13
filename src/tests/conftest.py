import pytest

from state_engine.config import PersonaConfig


def minimal_persona_dict():
    return {
        "scenario": {
            "patient_name": "Test Patient",
            "age": 40,
            "prompt": "A test scenario for automated testing.",
        },
        "severity_scale": {
            "trust_bands": {
                "trusting": {"min": 0.70, "max": 1.00, "description": "trusting desc"},
                "guarded": {"min": 0.45, "max": 0.69, "description": "guarded desc"},
                "distrustful": {"min": 0.20, "max": 0.44, "description": "distrustful desc"},
                "shut_down": {"min": 0.00, "max": 0.19, "description": "shut down desc"},
            },
            "saturation_bands": {
                "calm": {"min": 0.00, "max": 0.29, "description": "calm desc"},
                "strained": {"min": 0.30, "max": 0.59, "description": "strained desc"},
                "overwhelmed": {"min": 0.60, "max": 0.84, "description": "overwhelmed desc"},
                "breaking_point": {"min": 0.85, "max": 1.00, "description": "breaking point desc"},
            },
        },
        "audio_tags": {
            "SHOCK": ["[shocked]"],
            "ANGER": ["[sharp tone]"],
            "GRIEF": ["[voice breaking]"],
            "FEAR": ["[trembling voice]"],
            "BARGAINING": ["[pleading]"],
        },
        "personality": {
            "preferred_defense_mode": "SARCASM",
            "defense_trigger_trust": 0.35,
            "unacknowledged_threshold": 3,
            "acknowledgment_intensity_threshold": 0.3,
            "trust_penalty": -0.05,
            "saturation_penalty": 0.15,
        },
        "interruption": {
            "trigger_emotions": ["ANGER", "FEAR"],
            "min_intensity": 0.6,
            "min_seconds_before_interrupt": 3.0,
            "cooldown_seconds": 8.0,
            "base_probability": 0.4,
        },
        "initial_state": {
            "trust": 0.50,
            "saturation": 0.40,
            "emotion": {"primary": "SHOCK", "secondary": "GRIEF", "blend_weight": 0.2, "intensity": 0.65},
            "defense": {"mode": "NONE", "masking": "NONE"},
        },
        "flag_deltas": {
            "validating": {"trust": 0.10, "saturation": -0.08, "acknowledges": True},
            "silence_tolerance": {"trust": 0.05, "saturation": -0.04, "acknowledges": True},
            "premature_reassurance": {"trust": -0.08, "saturation": 0.10, "acknowledges": False},
            "jargon": {"trust": -0.04, "saturation": 0.06, "acknowledges": False},
            "logistics_first": {"trust": -0.04, "saturation": 0.06, "acknowledges": False},
            "interruption": {"trust": -0.08, "saturation": 0.12, "acknowledges": False},
        },
    }


@pytest.fixture
def persona():
    return PersonaConfig._from_dict(minimal_persona_dict())


@pytest.fixture
def persona_dict():
    return minimal_persona_dict()


@pytest.fixture
def tuning_file(tmp_path, persona_dict):
    import json
    path = tmp_path / "tuning.json"
    path.write_text(json.dumps(persona_dict))
    return str(path)