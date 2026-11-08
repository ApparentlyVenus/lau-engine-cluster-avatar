"""Rules added from the brief: the extra learner behaviours, blame and the
defensive state, frustration over unanswered questions, passive aggression,
and flag effects that depend on her current state."""

from dataclasses import replace

import pytest

from interpreter.parser import parse_turn_flags
from renderer.prompt import build_renderer_message
from state_engine.config import DEFAULT_REACTIONS, PersonaConfig
from state_engine.engine import apply_turn, build_initial_state, she_asked
from state_engine.patient_state import DefenseMode, EmotionMode, EmotionState
from state_engine.turn_flags import BRIEF_FLAGS, DEFAULT_BRIEF_DELTAS, TurnFlags
from state_engine.validate import validate_tuning


def told(state, persona):
    state, _ = apply_turn(state, TurnFlags(discloses_news=1.0), persona)
    return replace(state, unacknowledged_turns=0)


def with_emotion(state, emotion):
    return replace(state, emotion=EmotionState(primary=emotion, secondary=EmotionMode.CALM, blend_weight=0.2, intensity=0.6))


# ---- config ----------------------------------------------------------------

def test_brief_flags_default_when_file_lacks_them(persona):
    for name in BRIEF_FLAGS:
        t, s, ack = DEFAULT_BRIEF_DELTAS[name]
        rule = persona.flag_deltas[name]
        assert (rule.trust, rule.saturation, rule.acknowledges) == (t, s, ack)


def test_file_overrides_brief_flag_default(persona_dict):
    persona_dict["flag_deltas"]["blaming"] = {"trust": -0.3, "saturation": 0.3, "acknowledges": False}
    persona = PersonaConfig._from_dict(persona_dict)
    assert persona.flag_deltas["blaming"].trust == -0.3
    assert persona.flag_deltas["removes_blame"].trust == DEFAULT_BRIEF_DELTAS["removes_blame"][0]


def test_reactions_merge_with_defaults(persona_dict):
    persona_dict["reactions"] = {"SHOCK": {"jargon": 2.5}, "BARGAINING": {"validating": 0.5}}
    persona = PersonaConfig._from_dict(persona_dict)
    assert persona.reaction("SHOCK", "jargon") == 2.5
    assert persona.reaction("SHOCK", "silence_tolerance") == DEFAULT_REACTIONS["SHOCK"]["silence_tolerance"]
    assert persona.reaction("BARGAINING", "validating") == 0.5
    assert persona.reaction("BARGAINING", "jargon") == 1.0


# ---- validation ------------------------------------------------------------

def test_validator_accepts_brief_flags_and_reactions(persona_dict):
    persona_dict["flag_deltas"]["names_subtext"] = {"trust": 0.1, "saturation": -0.1, "acknowledges": True}
    persona_dict["reactions"] = {"DEFENSIVE": {"removes_blame": 2.0}, "PASSIVE_AGGRESSIVE": {"names_subtext": 1.5}}
    persona_dict["audio_tags"]["DEFENSIVE"] = ["[firmly]"]
    persona_dict["arc"] = {"blame_gain": 0.5, "frustration_after": 3, "frustration_trust": -0.05,
                           "weights": {"DEFENSIVE": 1.0}, "competence_deltas": {"repairs": 0.04}}
    persona_dict["personality"]["preferred_defense_mode"] = "PASSIVE_AGGRESSIVE"
    assert validate_tuning(persona_dict) == []


def test_validator_still_requires_core_flags(persona_dict):
    del persona_dict["flag_deltas"]["jargon"]
    assert any("flag_deltas.jargon" in e for e in validate_tuning(persona_dict))


@pytest.mark.parametrize("reactions, needle", [
    ({"HAPPY": {"jargon": 1.0}}, "invalid state"),
    ({"SHOCK": {"made_up": 1.0}}, "unknown flag"),
    ({"SHOCK": {"jargon": 5.0}}, "between 0 and 3"),
    ({"SHOCK": "lots"}, "must be an object"),
])
def test_validator_rejects_bad_reactions(persona_dict, reactions, needle):
    persona_dict["reactions"] = reactions
    assert any(needle in e for e in validate_tuning(persona_dict))


def test_validator_rejects_bad_frustration(persona_dict):
    persona_dict["arc"] = {"frustration_after": 1.5}
    assert any("frustration_after" in e for e in validate_tuning(persona_dict))


# ---- parser ----------------------------------------------------------------

def test_parser_reads_brief_flags():
    flags = parse_turn_flags('{"names_subtext": 0.7, "removes_blame": 0.8, "misreads_her": 0.3}')
    assert flags.names_subtext == 0.7 and flags.removes_blame == 0.8 and flags.misreads_her == 0.3
    assert flags.blaming == 0.0


# ---- reactions by state ----------------------------------------------------

def test_same_flag_lands_harder_in_shock(persona):
    state = told(build_initial_state(persona), persona)
    calm = with_emotion(state, EmotionMode.CALM)
    shocked = with_emotion(state, EmotionMode.SHOCK)
    after_calm, _ = apply_turn(calm, TurnFlags(logistics_first=1.0), persona)
    after_shock, _ = apply_turn(shocked, TurnFlags(logistics_first=1.0), persona)
    assert after_shock.trust < after_calm.trust
    assert after_shock.saturation > after_calm.saturation


def test_checking_understanding_helps_more_when_afraid(persona):
    state = told(build_initial_state(persona), persona)
    calm = with_emotion(state, EmotionMode.GRIEF)
    afraid = with_emotion(state, EmotionMode.FEAR)
    a, _ = apply_turn(calm, TurnFlags(checks_understanding=1.0), persona)
    b, _ = apply_turn(afraid, TurnFlags(checks_understanding=1.0), persona)
    assert b.trust - afraid.trust > a.trust - calm.trust


def test_defense_multiplier_stacks_with_emotion(persona):
    state = told(build_initial_state(persona), persona)
    plain = with_emotion(state, EmotionMode.GRIEF)
    shielded = replace(plain, defense=replace(plain.defense, mode=DefenseMode.SARCASM))
    a, _ = apply_turn(plain, TurnFlags(names_subtext=1.0), persona)
    b, _ = apply_turn(shielded, TurnFlags(names_subtext=1.0), persona)
    assert b.trust - shielded.trust > a.trust - plain.trust


# ---- blame and DEFENSIVE ---------------------------------------------------

def test_blaming_makes_her_defensive(persona):
    state = told(build_initial_state(persona), persona)
    state = replace(state, shock=0.0)
    state, _ = apply_turn(state, TurnFlags(blaming=1.0), persona)
    assert state.blame > 0.5
    assert state.emotion.primary == EmotionMode.DEFENSIVE


def test_defensive_before_the_news_too(persona):
    state = build_initial_state(persona)
    state, _ = apply_turn(state, TurnFlags(blaming=0.9), persona)
    assert EmotionMode.DEFENSIVE in (state.emotion.primary, state.emotion.secondary)


def test_not_your_fault_clears_blame(persona):
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, TurnFlags(blaming=1.0), persona)
    before = state.blame
    state, _ = apply_turn(state, TurnFlags(removes_blame=1.0), persona)
    assert state.blame < before / 2


def test_blame_fades_on_its_own(persona):
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, TurnFlags(blaming=1.0), persona)
    first = state.blame
    state, _ = apply_turn(state, TurnFlags(), persona)
    assert 0 < state.blame < first


# ---- unanswered questions --------------------------------------------------

def test_she_asked_reads_her_last_line():
    assert she_asked(["Learner: hi", "Patient: [softly] Is it serious?"])
    assert not she_asked(["Patient: Is it serious?", "Learner: yes", "Patient: Okay."])
    assert she_asked(["Patient: What now?", "Learner: um"])
    assert not she_asked([])


def test_answering_resets_the_count(persona):
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, TurnFlags(), persona, she_asked=True)
    assert state.unanswered == 1
    state, _ = apply_turn(state, TurnFlags(answers_question=1.0), persona, she_asked=True)
    assert state.unanswered == 0


def test_count_only_moves_when_she_asked(persona):
    state = told(build_initial_state(persona), persona)
    state, _ = apply_turn(state, TurnFlags(), persona, she_asked=True)
    state, _ = apply_turn(state, TurnFlags(), persona, she_asked=False)
    assert state.unanswered == 1


def test_repeated_unanswered_questions_cost_trust(persona):
    start = told(build_initial_state(persona), persona)
    asked = ignored = start
    for _ in range(3):
        asked, _ = apply_turn(asked, TurnFlags(), persona, she_asked=True)
        ignored, _ = apply_turn(ignored, TurnFlags(), persona, she_asked=False)
    assert asked.unanswered == 3
    assert asked.trust < ignored.trust


def test_frustration_turns_passive_aggressive(persona):
    state = told(build_initial_state(persona), persona)
    state = replace(state, trust=0.42)
    for _ in range(2):
        state, _ = apply_turn(state, TurnFlags(), persona, she_asked=True)
    assert state.defense.mode == DefenseMode.PASSIVE_AGGRESSIVE


def test_frustration_line_in_renderer_message(persona):
    state = told(build_initial_state(persona), persona)
    assert "unanswered" not in build_renderer_message(persona, state, "ok")
    state = replace(state, unanswered=2)
    assert "the last 2 went unanswered" in build_renderer_message(persona, state, "ok")


def test_layla_file_is_valid_and_complete():
    import json
    from pathlib import Path

    path = Path(__file__).parents[1] / "state_engine" / "tuning" / "tuning.json"
    data = json.loads(path.read_text())
    assert validate_tuning(data) == []
    assert "DEFENSIVE" in data["audio_tags"]
    persona = PersonaConfig.from_file(str(path))
    assert set(BRIEF_FLAGS) <= set(persona.flag_deltas)  # from the defaults


# ---- diagnostics trace -----------------------------------------------------

def test_trace_explains_the_turn(persona):
    state = told(build_initial_state(persona), persona)
    state = with_emotion(state, EmotionMode.SHOCK)
    trace = {}
    after, _ = apply_turn(state, TurnFlags(logistics_first=1.0, blaming=0.5), persona, she_asked=True, trace=trace)
    flags = {f["flag"]: f for f in trace["flags"]}
    assert flags["logistics_first"]["multiplier"] == DEFAULT_REACTIONS["SHOCK"]["logistics_first"]
    assert trace["reacting_in"] == ["SHOCK"] and trace["she_asked"] and not trace["answered"]
    assert trace["blame"]["added"] > 0
    assert list(trace["emotion_scores"])[0] == after.emotion.primary.name


def test_trace_is_optional_and_harmless(persona):
    state = build_initial_state(persona)
    a, _ = apply_turn(state, TurnFlags(validating=0.6), persona)
    b, _ = apply_turn(state, TurnFlags(validating=0.6), persona, trace={})
    assert a == b
