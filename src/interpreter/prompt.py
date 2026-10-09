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

Timing: the learner's turn may contain [pause 1.4s] markers, and there may be a "Measured timing" list. These are measured from the audio, not guessed. Use them only to judge silence_tolerance and to read the learner's words in context:
- A pause the learner leaves after naming her emotion or after hard news, or a long wait before speaking after she has said something painful, supports silence_tolerance.
- Hesitation inside a sentence (pausing mid-phrase, filler words) is not silence_tolerance. It is neutral; do not score it as anything.
- Starting to speak almost immediately after an emotional line from her is not silence_tolerance.
Never score interruption; talking over her is measured separately. If there are no pause markers and no timing list, timing is unknown: score from the words alone and never guess at pauses or tone of voice. Consider what the patient herself just said before scoring the learner's response.

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

Patient: "[voice breaking] I don't understand any of this."
Learner: "I'm so sorry. [pause 2.4s] This is a lot."
Measured timing: started speaking 2.1s after she finished.
{"validating": 0.7, "silence_tolerance": 0.7}

Patient: "[voice breaking] I don't understand any of this."
Learner: "So the [pause 1.2s] um the scan [pause 0.9s] is on Monday."
Measured timing: started speaking 0.3s after she finished.
{"logistics_first": 0.8}

Return ONLY a raw JSON object containing the keys that scored above 0. Never use markdown or code fences. Omit every key that scored 0. If nothing applies, return {}.
"""


def build_interpreter_message(
    persona,
    transcript: str,
    history: list[str],
    max_history_lines: int = 4,
    timing: str | None = None,
) -> str:
    """`transcript` may already carry [pause Ns] markers; `timing` is the
    measured-timing list from pipeline.timing.timing_block, or None."""
    trimmed = history[-max_history_lines:] if history else []
    history_block = "\n".join(f"- {line}" for line in trimmed) if trimmed else "(no prior turns)"
    timing_section = f"\n\nMeasured timing:\n{timing}" if timing else ""
    return f"""{build_scenario_block(persona)}

Conversation history (most recent last):
{history_block}

Learner's most recent turn:
"{transcript}"{timing_section}

Classify this turn."""