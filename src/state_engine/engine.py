from state_engine.config import PersonaConfig
from state_engine.patient_state import PatientState, EmotionState, DefenseState, EmotionMode, DefenseMode
from state_engine.turn_flags import TurnFlags


def build_initial_state(persona: PersonaConfig) -> PatientState:
    init = persona.raw_initial_state
    emotion = EmotionState(
        primary=EmotionMode[init["emotion"]["primary"]],
        secondary=EmotionMode[init["emotion"]["secondary"]],
        blend_weight=init["emotion"]["blend_weight"],
        intensity=init["emotion"]["intensity"],
    )
    defense = DefenseState(
        mode=DefenseMode[init["defense"]["mode"]],
        masking=EmotionMode[init["defense"]["masking"]],
    )
    return PatientState(
        trust=init["trust"],
        saturation=init["saturation"],
        unacknowledged_turns=0,
        turn_count=0,
        emotion=emotion,
        defense=defense,
        competence=init.get("competence", 0.6),
    )


def she_asked(history: list[str]) -> bool:
    """Was her last line a question? (History lines are "Learner: ..." and
    "Patient: ...".) Audio tags in brackets are ignored."""
    for line in reversed(history):
        if line.startswith("Patient:"):
            return "?" in line
        if line.startswith("Learner:"):
            continue
    return False


def apply_turn(state: PatientState, flags: TurnFlags, persona: PersonaConfig,
               she_asked: bool = False, trace: dict | None = None) -> tuple[PatientState, bool]:
    """One learner turn. Returns (new state, whether the patient escalated).

    she_asked: the patient's previous line was a question, so this turn either
    answers it or leaves it hanging (repeated unanswered questions frustrate).
    trace: if given, filled with how each rule moved the state (diagnostics).
    """
    t = trace if trace is not None else {}
    if state.ended:
        t["skipped"] = "the patient has already left"
        return state, False
    deltas = persona.flag_deltas
    personality = persona.personality
    arc = persona.arc

    trust_delta = 0.0
    saturation_delta = 0.0
    turn_acknowledges = False

    # The same words land differently depending on where she is right now.
    states_now = [state.emotion.primary.name]
    if state.defense.mode != DefenseMode.NONE:
        states_now.append(state.defense.mode.name)
    t["reacting_in"] = states_now
    t["flags"] = []

    for flag_name, intensity in flags.behaviours().items():
        if intensity <= 0:
            continue
        rule = deltas.get(flag_name)
        if rule is None:
            continue
        mult = 1.0
        for name in states_now:
            mult *= persona.reaction(name, flag_name)
        trust_delta += rule.trust * intensity * mult
        saturation_delta += rule.saturation * intensity * mult
        acknowledges = rule.acknowledges and intensity >= personality.acknowledgment_intensity_threshold
        if acknowledges:
            turn_acknowledges = True
        t["flags"].append({
            "flag": flag_name, "intensity": round(intensity, 2), "multiplier": round(mult, 2),
            "trust": round(rule.trust * intensity * mult, 3), "saturation": round(rule.saturation * intensity * mult, 3),
            "acknowledges": acknowledges,
        })

    # Her questions: answered resets the count, ignored adds to it, and past
    # the limit every further ignored question costs trust.
    unanswered = state.unanswered
    if she_asked:
        unanswered = 0 if flags.answers_question >= 0.5 else unanswered + 1
    frustrated = arc.frustration_after > 0 and unanswered >= arc.frustration_after
    t["she_asked"] = she_asked
    t["answered"] = flags.answers_question >= 0.5
    if frustrated and she_asked and flags.answers_question < 0.5:
        trust_delta += arc.frustration_trust
        saturation_delta += arc.frustration_saturation
        t["frustration"] = {"trust": arc.frustration_trust, "saturation": arc.frustration_saturation}

    # Blame: "did I cause this?" Builds with blaming, eases when the learner
    # takes it off her, fades on its own.
    blame = _clamp(
        state.blame * (1 - arc.blame_decay)
        + arc.blame_gain * flags.blaming
        - arc.blame_relief * flags.removes_blame
    )
    t["blame"] = {
        "faded": round(-state.blame * arc.blame_decay, 3),
        "added": round(arc.blame_gain * flags.blaming, 3),
        "removed": round(-arc.blame_relief * flags.removes_blame, 3),
    }

    # The news itself, once.
    discloses = flags.discloses_news >= 0.5 and not state.news_delivered
    news_delivered = state.news_delivered or discloses
    if discloses:
        trust_delta += arc.disclosure_trust
        saturation_delta += arc.disclosure_saturation
        t["disclosure"] = {"trust": arc.disclosure_trust, "saturation": arc.disclosure_saturation}

    new_trust = _clamp(state.trust + trust_delta)
    new_saturation = _clamp(state.saturation + saturation_delta)
    new_unacknowledged = 0 if turn_acknowledges else state.unacknowledged_turns + 1
    if not news_delivered and not turn_acknowledges:
        # Small talk before the news is not "ignoring her feelings".
        new_unacknowledged = state.unacknowledged_turns

    escalated = False
    if new_unacknowledged >= personality.unacknowledged_threshold:
        new_trust = _clamp(new_trust + personality.trust_penalty)
        new_saturation = _clamp(new_saturation + personality.saturation_penalty)
        new_unacknowledged = 0
        escalated = True
        t["escalation"] = {"trust": personality.trust_penalty, "saturation": personality.saturation_penalty}

    values = {**flags.behaviours(), "answers_question": flags.answers_question}
    competence_parts = {
        name: round(arc.competence_deltas[name] * v, 3)
        for name, v in values.items() if v > 0 and arc.competence_deltas.get(name)
    }
    t["competence"] = competence_parts
    new_competence = _clamp(state.competence + sum(competence_parts.values()))

    if discloses:
        new_shock = arc.shock_peak
    elif news_delivered:
        relief = sum(arc.shock_relief.get(n, 0.0) * v for n, v in values.items() if v > 0)
        prolong = sum(arc.shock_prolong.get(n, 0.0) * v for n, v in values.items() if v > 0)
        new_shock = _clamp(state.shock - max(0.0, arc.shock_decay + relief - prolong))
        t["shock"] = {"decay": arc.shock_decay, "relief": round(relief, 3), "prolong": round(prolong, 3)}
    else:
        new_shock = 0.0

    low = state.low_trust_turns + 1 if new_trust <= arc.walkout_trust else 0
    ended = arc.walkout_turns > 0 and low >= arc.walkout_turns

    new_turn_count = state.turn_count + 1
    new_emotion = _update_emotion(new_trust, new_saturation, new_competence, new_shock, news_delivered, arc, blame)
    new_defense = _update_defense(new_trust, new_saturation, new_emotion, personality, frustrated)
    t["emotion_scores"] = {
        e.name: round(v, 3) for e, v in sorted(
            emotion_scores(new_trust, new_saturation, new_competence, new_shock, news_delivered, arc, blame).items(),
            key=lambda kv: kv[1], reverse=True)
    }
    if ended:
        t["walkout"] = True

    new_state = PatientState(
        trust=new_trust,
        saturation=new_saturation,
        unacknowledged_turns=new_unacknowledged,
        turn_count=new_turn_count,
        emotion=new_emotion,
        defense=new_defense,
        competence=new_competence,
        news_delivered=news_delivered,
        shock=new_shock,
        low_trust_turns=low,
        ended=ended,
        blame=blame,
        unanswered=unanswered,
    )
    return new_state, escalated


def emotion_scores(trust: float, saturation: float, competence: float, shock: float,
                   news_delivered: bool, arc, blame: float = 0.0) -> dict[EmotionMode, float]:
    """Raw score per emotion; see the table in state_engine.config."""
    t, s, c = trust, saturation, competence
    w = arc.weights
    if not news_delivered:
        raw = {
            EmotionMode.CALM: t * (1 - s),
            EmotionMode.FEAR: arc.pre_news_anxiety,
            # Squared: before the news, anger needs real friction (rudeness),
            # not just a bit of tension.
            EmotionMode.ANGER: s * (1 - t) ** 2,
        }
    else:
        f = 1 - shock
        raw = {
            EmotionMode.SHOCK: shock,
            EmotionMode.ANGER: s * (1 - t),
            EmotionMode.GRIEF: f * s * t,
            EmotionMode.FEAR: f * s * (1 - c),
            EmotionMode.BARGAINING: f * s * max(0.0, 1 - 2 * abs(t - 0.55)),
            EmotionMode.CALM: f * t * (1 - s),
        }
    if blame > 0:
        raw[EmotionMode.DEFENSIVE] = blame
    scores = {e: _clamp(v * w.get(e.name, 1.0)) for e, v in raw.items()}
    # Two entries at least, so there is always an undertone.
    for e in (EmotionMode.CALM, EmotionMode.FEAR):
        scores.setdefault(e, 0.0)
    return scores


def _update_emotion(trust: float, saturation: float, competence: float, shock: float,
                    news_delivered: bool, arc, blame: float = 0.0) -> EmotionState:
    raw = emotion_scores(trust, saturation, competence, shock, news_delivered, arc, blame)
    ranked = sorted(raw.items(), key=lambda item: item[1], reverse=True)
    primary, primary_value = ranked[0]
    secondary, secondary_value = ranked[1]

    total = primary_value + secondary_value
    blend_weight = secondary_value / total if total > 0 else 0.0
    intensity = _clamp(primary_value)

    return EmotionState(primary=primary, secondary=secondary, blend_weight=blend_weight, intensity=intensity)


# Frustration shows as passive aggression a little before trust is low enough
# for her usual defense.
FRUSTRATION_DEFENSE_MARGIN = 0.15


def _update_defense(trust: float, saturation: float, emotion: EmotionState, personality,
                    frustrated: bool = False) -> DefenseState:
    if frustrated and trust < personality.defense_trigger_trust + FRUSTRATION_DEFENSE_MARGIN:
        return DefenseState(mode=DefenseMode.PASSIVE_AGGRESSIVE, masking=emotion.primary)
    if trust >= personality.defense_trigger_trust:
        return DefenseState(mode=DefenseMode.NONE, masking=EmotionMode.NONE)
    return DefenseState(mode=personality.preferred_defense_mode, masking=emotion.primary)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
