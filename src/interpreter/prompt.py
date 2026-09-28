from state_engine.config import build_scenario_block

INTERPRETER_TASK_PROMPT = """You are a classifier for a clinical communication training simulator. You will be given a description of a patient scenario and a learner's most recent turn of dialogue. Score that turn against six categories, each from 0 to 1, where 0 means "not present at all" and 1 means "strongly, unambiguously present."

Categories:

validating: the learner named or acknowledged the patient's emotion.
silence_tolerance: the learner let a pause sit rather than immediately re-filling it after a difficult moment.
premature_reassurance: the learner offered comfort or minimized the situation before the patient was ready for it, even if well-intentioned (e.g. "don't worry", "it will be fine"). Stating a next step or a plan is not reassurance by itself; that belongs under logistics_first.
jargon: the learner used clinical language without a plain-language explanation.
logistics_first: the learner moved to next steps before acknowledging the emotional weight of the moment.
disrespect: the learner was condescending, dismissive, mocking, or cruel toward her, independent of the clinical content of what they said (e.g. "are you slow?", laughing at her diagnosis, mocking her fear).

You only see text, so never infer anything about timing, tone of voice, or talking over her.

Consider what the patient herself just said before scoring the learner's response. If she directly asked a question or requested information (e.g. "what happens next?"), a direct answer to that request is not premature or out of place. Do not score logistics_first, jargon, or similar categories against a response that is directly answering what she just asked for.

A turn can score above 0 on more than one category. Most turns score 0 on most categories.

Return ONLY a raw JSON object containing the categories that scored above 0. Never use markdown or code fences. Omit every category that scored 0. If nothing applies, return {}.

Example: {"validating": 0.6, "logistics_first": 0.3}
"""


def build_interpreter_message(persona, transcript: str, history: list[str], max_history_lines: int = 4) -> str:
    trimmed = history[-max_history_lines:] if history else []
    history_block = "\n".join(f"- {line}" for line in trimmed) if trimmed else "(no prior turns)"
    return f"""{build_scenario_block(persona)}

Conversation history (most recent last):
{history_block}

Learner's most recent turn:
"{transcript}"

Classify this turn."""