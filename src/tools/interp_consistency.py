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
]
REPEATS = 8
THRESHOLD = 0.3
CONCURRENCY = 8


async def classify(persona, history, text, semaphore):
    async with semaphore:
        raw = await call_interpreter(build_interpreter_message(persona, text, history))
    try:
        flags = parse_turn_flags(raw)
    except InterpreterParseError:
        return None
    return {name: value for name, value in vars(flags).items() if value >= THRESHOLD}


async def main(persona_path: str):
    persona = PersonaConfig.from_file(persona_path)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    for label, history, text in CASES:
        results = await asyncio.gather(*(classify(persona, history, text, semaphore) for _ in range(REPEATS)))
        groups: dict[str, list[dict]] = defaultdict(list)
        for result in results:
            if result is None:
                groups["(parse error)"].append({})
            else:
                key = ", ".join(sorted(result)) or "(nothing)"
                groups[key].append(result)

        print(f"\n[{label}] {text!r}")
        for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            averages = ""
            if items and items[0]:
                names = sorted(items[0])
                averages = "  " + " ".join(f"{n}={sum(i[n] for i in items) / len(items):.2f}" for n in names)
            print(f"  {len(items)}/{REPEATS}  {key}{averages}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))