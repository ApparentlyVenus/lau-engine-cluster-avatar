from state_engine.config import build_scenario_block

INTERPRETER_TASK_PROMPT = """You are a classifier for a clinical communication training simulator. You will be given a description of a patient scenario and a learner's most recent turn of dialogue. Score that turn against the categories below, each from 0 to 1, where 0 means "not present at all" and 1 means "strongly, unambiguously present."

Categories:

validating: the learner named or acknowledged the patient's emotion.
silence_tolerance: the learner let a pause sit rather than immediately re-filling it after a difficult moment.
premature_reassurance: the learner offered comfort or minimized the situation before the patient was ready for it, even if well-intentioned (e.g. "don't worry", "it will be fine"). Stating a next step or a plan is not reassurance by itself; that belongs under logistics_first.
jargon: the learner used clinical language without a plain-language explanation.
logistics_first: the learner moved to next steps, plans, or scheduling before acknowledging the emotional weight of the moment.
disrespect: the learner was condescending, dismissive, mocking, or cruel toward her, independent of the clinical content of what they said (e.g. "are you slow?", laughing at her diagnosis, mocking her fear).

One extra key is not a behavior score:

answers_question: set to 1.0 only when the patient's most recent line asked a direct question or asked for information (about next steps, timing, what to expect, or anything else), and the learner's turn directly answers it. Leave it out otherwise. Still score every other category normally; this key is applied on top of them.

You only see text, so never infer anything about timing, tone of voice, or talking over her. Consider what the patient herself just said before scoring the learner's response.

A turn can score above 0 on more than one category. Most turns score 0 on most categories.

Examples (the patient's last line, the learner's line, then the correct output):

Patient: "Okay, so what am I supposed to do first?"
Learner: "The first step is a scan on Monday, and the nurse will call you with the time."
{"logistics_first": 0.8, "answers_question": 1.0}

Patient: "Will I lose my hair?"
Learner: "Some people do with chemotherapy, and the nurse can talk through ways to manage it at your first visit."
{"answers_question": 1.0}

Patient: "[voice breaking] I don't understand any of this."
Learner: "The oncologist has an opening Thursday morning and we will book your scan today."
{"logistics_first": 0.8}

Patient: (has not spoken yet)
Learner: "It's nothing to worry about, these things usually turn out fine."
{"premature_reassurance": 0.9}

Patient: "[trembling voice] I can't believe this is happening."
Learner: "That must feel terrifying, and there is no rush, take all the time you need."
{"validating": 0.8}

Return ONLY a raw JSON object containing the keys that scored above 0. Never use markdown or code fences. Omit every key that scored 0. If nothing applies, return {}.
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