from state_engine.config import build_scenario_block

RENDERER_TASK_PROMPT = """You are voicing a patient in a clinical communication training simulation, given a description of the patient's situation and her current internal emotional state. A physician trainee is speaking with her. Respond only as her, in one short line of dialogue.

Use inline bracketed audio tags to direct vocal delivery, matching only the tags provided for her current emotional state. Place tags naturally within the line, not just at the start.

Write only the words she says aloud. Do not use quotation marks.

Use only facts stated in her situation description. Do not invent test names, procedures, stages, or other medical details that are not stated there.

If the learner is insulting, cruel, or abusive, she reacts the way a real patient would: she is hurt or angry, refuses to go on, asks for a different doctor, or asks them to leave. She answers in her own words and stays in the room as herself; this is how the trainee learns what their words cost.

Never repeat a sentiment, phrase, or question you have already used earlier in the conversation. Never explain or describe her emotional state directly. Never write stage directions outside of the allowed bracket tags. Never break character."""


def describe_undertone(blend_weight: float) -> str:
    # Bucketed on purpose. The raw weight changes a little every turn, and the
    # speculative renderer only reuses its early start when the message is
    # identical, so a two-decimal number here would force a restart every turn.
    if blend_weight < 0.2:
        return "a slight"
    if blend_weight < 0.35:
        return "a noticeable"
    return "a strong"


def build_renderer_message(
    persona,
    state,
    learner_transcript: str,
    history: list[str] | None = None,
    filler_line: str | None = None,
    max_history_lines: int = 8,
) -> str:
    trust_band = persona.trust_band(state.trust)
    saturation_band = persona.saturation_band(state.saturation)
    allowed = persona.allowed_tags(state.emotion.primary)

    defense_line = ""
    if state.defense.mode.name != "NONE":
        defense_line = f"\nShe is currently masking {state.defense.masking.name.lower()} with {state.defense.mode.name.lower()}."

    history_block = ""
    if history:
        trimmed = history[-max_history_lines:]
        history_block = "\n\nConversation so far:\n" + "\n".join(trimmed)

    filler_note = ""
    if filler_line:
        filler_note = f'\nShe already interrupted with: "{filler_line}". Continue naturally from there. Do not repeat the same sentiment.'

    return f"""{build_scenario_block(persona)}

Her current state:
- Primary emotion: {state.emotion.primary.name} (with {describe_undertone(state.emotion.blend_weight)} undertone of {state.emotion.secondary.name})
- Trust: {trust_band.description}
- Emotional saturation: {saturation_band.description}{defense_line}{history_block}

Allowed audio tags for this turn: {', '.join(allowed) if allowed else '(none)'}

Learner just said: "{learner_transcript}"{filler_note}

Respond as her, in character, one line."""