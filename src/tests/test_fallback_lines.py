"""Fallback lines when the model breaks character (pipeline/fallback.py)."""

import random
from types import SimpleNamespace

import pytest

from pipeline.fallback import FALLBACK_LINES, OUT_OF_CHARACTER_FALLBACK, FallbackLines, fallback_key, is_out_of_character


def state(emotion="CALM", trust=0.55, news=True):
    return SimpleNamespace(trust=trust, news_delivered=news, emotion=SimpleNamespace(primary=SimpleNamespace(name=emotion)))


@pytest.mark.parametrize("text,ooc", [
    ("I'm not able to continue this roleplay.", True),
    ("The learner's dialogue contains abuse I can't engage with.", True),
    ("As an AI, I won't continue.", True),
    ("I was made by Anthropic and I can't continue.", True),
    ("Hello, I'm Claude Haddad.", False),  # a patient may be called Claude
    ("I need to step out of the role for a moment.", True),
    ("[sharp tone] Get out. I want a different doctor.", False),
    ("What's the worst-case scenario here?", False),
    ("I can't believe you just said that to me.", False),
    ("My daughter has a role in the school play.", False),
])
def test_detection(text, ooc):
    assert is_out_of_character(text) is ooc


def test_line_fits_the_moment():
    assert fallback_key(None) == "BEFORE_NEWS"
    assert fallback_key(state(news=False)) == "BEFORE_NEWS"  # nothing that assumes a diagnosis
    assert fallback_key(state("GRIEF")) == "GRIEF"
    assert fallback_key(state("DEFENSIVE")) == "DEFENSIVE"
    assert fallback_key(state("GRIEF", trust=0.1)) == "SHUT_DOWN"
    assert fallback_key(state("SOMETHING_NEW")) == "CALM"


def test_no_repeats_until_every_line_is_used():
    fb = FallbackLines(rng=random.Random(1))
    pool = FALLBACK_LINES["GRIEF"]
    picked = [fb.pick(state("GRIEF")) for _ in pool]
    assert sorted(picked) == sorted(pool)
    assert fb.pick(state("GRIEF")) in pool  # then it starts again
    assert fb.count == len(pool) + 1


def test_before_news_lines_never_mention_the_diagnosis():
    for line in FALLBACK_LINES["BEFORE_NEWS"]:
        assert not any(w in line.lower() for w in ("cancer", "treatment", "options", "news"))


def test_old_line_is_kept_for_when_trust_is_gone():
    assert OUT_OF_CHARACTER_FALLBACK in FALLBACK_LINES["SHUT_DOWN"]


def test_no_fallback_line_trips_the_detector():
    for pool in FALLBACK_LINES.values():
        for line in pool:
            assert not is_out_of_character(line), line
