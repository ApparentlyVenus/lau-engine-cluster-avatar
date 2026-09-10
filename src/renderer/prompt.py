from state_engine.config import build_scenario_block

RENDERER_TASK_PROMPT = """You are voicing a patient in a clinical communication training simulation, given a description of the patient's situation and her current internal emotional state. A physician trainee is speaking with her. Respond only as her, in one short line of dialogue.

Use inline bracketed audio tags to direct vocal delivery, matching only the tags provided for her current emotional state. Place tags naturally within the line, not just at the start.

Never explain or describe her emotional state directly. Never write stage directions outside of the allowed bracket tags. Never break character."""

def build_renderer_message(persona, state, learner_transcript: str, filler_line: str | None = None) -> str:
    trust_band = persona.trust_band(state.trust)
    saturation_band = persona.saturation_band(state.saturation)
    allowed = persona.allowed_tags(state.emotion.primary)

    defense_line = ""
    if state.defense.mode.name != "NONE":
        defense_line = f"\nShe is currently masking {state.defense.masking.name.lower()} with {state.defense.mode.name.lower()}."

    filler_note = ""
    if filler_line:
        filler_note = f'\nShe already interrupted with: "{filler_line}". Continue naturally from there. Do not repeat the same sentiment.'

    return f"""{build_scenario_block(persona)}

Her current state:
- Primary emotion: {state.emotion.primary.name} (with an undertone of {state.emotion.secondary.name}, blend weight {state.emotion.blend_weight:.2f})
- Trust: {trust_band.description}
- Emotional saturation: {saturation_band.description}{defense_line}

Allowed audio tags for this turn: {', '.join(allowed) if allowed else '(none)'}

Learner just said: "{learner_transcript}"{filler_note}

Respond as her, in character, one line."""