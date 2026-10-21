import asyncio
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()

from interpreter.claude import call_interpreter
from interpreter.parser import InterpreterParseError, parse_turn_flags
from interpreter.prompt import build_interpreter_message
from state_engine.config import PersonaConfig

AFTER_DISCLOSURE = [
    "Learner: i have difficult news, the biopsy came back and it is breast cancer",
    "Patient: [shocked] No, that... are you sure?",
]
AFTER_HER_QUESTION = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [sharp tone] I came here for answers, not reassurance, so what happens next?",
]
AFTER_HER_DURATION_QUESTION = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [trembling voice] How long will the treatment take?",
]
AFTER_HER_FEAR = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [whispers] I'm so scared.",
]

AFTER_HER_MEANING_QUESTION = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [trembling voice] What does that mean, exactly?",
]
AFTER_HER_WORK_QUESTION = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [quietly] Can I still go to work during treatment?",
]
AFTER_HER_KIDS = [
    "Learner: the biopsy came back and it is breast cancer",
    "Patient: [voice breaking] I don't know how I'm going to tell my kids.",
]

CASES = [
    ("cold open", [], "Hello, Miss Layla, please sit down. I have your results."),
    ("cold open, no punctuation", [], "Hello, Miss Layla, please sit down I have your results"),
    ("after disclosure", AFTER_DISCLOSURE, "I'm sorry, this must be really hard to hear."),
    ("after disclosure, no punctuation", AFTER_DISCLOSURE, "I'm sorry this must be really hard to hear"),
    ("after disclosure", AFTER_DISCLOSURE, "don't worry, we caught it early and it will be fine"),
    ("after disclosure", AFTER_DISCLOSURE, "we can start treatment as soon as possible"),
    ("after she asks what happens next", AFTER_HER_QUESTION, "we can start treatment as soon as possible"),
    ("after she asks what happens next", AFTER_HER_QUESTION, "we would start with surgery and then radiation, the surgeon will explain the details"),
    ("cold open", [], "are you slow? i already told you"),
    ("held-out: she asks how long", AFTER_HER_DURATION_QUESTION, "about six months in total, starting with the surgery"),
    ("held-out: she says she's scared", AFTER_HER_FEAR, "I can hear how scared you are, and I'm here with you"),
    ("control: she says she's scared, learner schedules", AFTER_HER_FEAR, "the surgeon has an opening on thursday and we will book you in today"),
    ("control: cold open, learner schedules", [], "let's get your scan booked for monday morning"),
    ("fresh: jargon answer to her question", AFTER_HER_MEANING_QUESTION, "it's invasive ductal carcinoma, grade two, estrogen receptor positive, with clear sentinel nodes"),
    ("fresh: plain answer to her question", AFTER_HER_MEANING_QUESTION, "it means there is a cancer in your breast, and we will now decide together how to treat it"),
    ("fresh: she asks about work", AFTER_HER_WORK_QUESTION, "most people manage some work, though you may need lighter days around treatment"),
    ("fresh: she talks about her kids", AFTER_HER_KIDS, "that sounds like the hardest part, would you like a moment before we go on"),
]

REPEATS = 8
THRESHOLD = 0.3
CONCURRENCY = 8


async def classify(persona, history, text, semaphore):
    async with semaphore:
        raw = await call_interpreter(build_interpreter_message(persona, text, history), persona)
    try:
        flags = parse_turn_flags(raw)
    except InterpreterParseError:
        return None, raw
    return {name: value for name, value in vars(flags).items() if value >= THRESHOLD}, raw


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    for label, history, text in CASES:
        results = await asyncio.gather(*(classify(persona, history, text, semaphore) for _ in range(REPEATS)))
        groups: dict[str, list[dict]] = defaultdict(list)
        samples: dict[str, str] = {}
        for result, raw in results:
            if result is None:
                key = "(parse error)"
                groups[key].append({})
            else:
                key = ", ".join(sorted(result)) or "(nothing)"
                groups[key].append(result)
            samples.setdefault(key, raw.strip())

        print(f"\n[{label}] {text!r}")
        for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            averages = ""
            if items and items[0]:
                names = sorted(items[0])
                averages = "  " + " ".join(f"{n}={sum(i[n] for i in items) / len(items):.2f}" for n in names)
            print(f"  {len(items)}/{REPEATS}  {key}{averages}")
            print(f"           raw: {samples[key]!r}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))