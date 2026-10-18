import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline.build import SessionOptions
from state_engine.validate import validate_tuning
from web.characters import CharacterError, CharacterStore, slugify
from web.server import create_app

SHIPPED = Path(__file__).parents[1] / "state_engine" / "tuning" / "tuning.json"


@pytest.fixture
def folder(tmp_path):
    shutil.copy(SHIPPED, tmp_path / "tuning.json")
    return tmp_path


@pytest.fixture
def client(folder):
    return TestClient(create_app(str(folder), "tuning", SessionOptions(tts=False)))


def layla():
    return json.loads(SHIPPED.read_text())


# --- validation covers every section ----------------------------------------

def test_shipped_file_is_valid():
    assert validate_tuning(layla()) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d.update(typo={}), "Unknown top-level keys"),
    (lambda d: d["timing"].update(fast_wpm=50), "slow_wpm must be below"),
    (lambda d: d["timing"].update(commit_after_unfinished_s=0.5), "commit_after_unfinished_s"),
    (lambda d: d["timing"].update(bogus=1), "timing has unknown keys"),
    (lambda d: d["voice"].update(stability=2), "voice.stability"),
    (lambda d: d["voice"].update(model="gpt"), "voice.model"),
    (lambda d: d["flag_deltas"]["jargon"].update(trust=5), "flag_deltas.jargon.trust"),
    (lambda d: d["personality"].update(trust_penalty="x"), "personality.trust_penalty"),
    (lambda d: d["scenario"].update(patient_name="  "), "scenario.patient_name"),
    (lambda d: d["initial_state"].update(trust="high"), "wrong value type"),
])
def test_validation_catches(mutate, expect):
    data = layla()
    mutate(data)
    assert any(expect in e for e in validate_tuning(data)), validate_tuning(data)


def test_timing_and_voice_are_optional():
    data = layla()
    del data["timing"], data["voice"]
    assert validate_tuning(data) == []


# --- store ------------------------------------------------------------------

def test_store_create_save_delete(folder):
    store = CharacterStore(folder)
    data = layla()
    data["scenario"]["patient_name"] = "Rami Khoury"
    made = store.create(data)
    assert made["id"] == "rami_khoury" and made["name"] == "Rami Khoury"
    assert store.create(data)["id"] == "rami_khoury_2"

    data["scenario"]["age"] = 61
    store.save("rami_khoury", data)
    assert store.get("rami_khoury")["scenario"]["age"] == 61

    store.delete("rami_khoury")
    assert "rami_khoury" not in store.ids()
    assert list((folder / "deleted").glob("rami_khoury-*.json"))


def test_store_refuses_invalid_and_bad_ids(folder):
    store = CharacterStore(folder)
    bad = layla()
    bad["initial_state"]["trust"] = 3
    with pytest.raises(CharacterError) as e:
        store.save("tuning", bad)
    assert e.value.status == 422 and e.value.errors
    assert store.get("tuning")["initial_state"]["trust"] == 0.5  # untouched
    for evil in ("../x", "A B", ""):
        with pytest.raises(CharacterError):
            store.path(evil)


def test_cannot_delete_last(folder):
    with pytest.raises(CharacterError):
        CharacterStore(folder).delete("tuning")


def test_missing_voice_is_a_warning_not_an_error(folder):
    store = CharacterStore(folder)
    data = layla()
    data["voice"]["voice_id"] = ""
    s = store.save("tuning", data)
    assert s["errors"] == [] and any("voice_id" in w for w in s["warnings"])


def test_slugify():
    assert slugify("Mrs. Layla Haddad") == "mrs_layla_haddad"
    assert slugify("!!!") == "patient"


# --- API --------------------------------------------------------------------

def test_api_roundtrip(client):
    r = client.get("/api/characters")
    assert [c["id"] for c in r.json()] == ["tuning"]

    data = layla()
    data["scenario"]["patient_name"] = "Nadia Saleh"
    made = client.post("/api/characters", json=data).json()
    assert made["id"] == "nadia_saleh"

    data["personality"]["unacknowledged_threshold"] = 5
    assert client.put("/api/characters/nadia_saleh", json=data).status_code == 200
    assert client.get("/api/characters/nadia_saleh").json()["personality"]["unacknowledged_threshold"] == 5

    data["personality"]["unacknowledged_threshold"] = 0
    r = client.put("/api/characters/nadia_saleh", json=data)
    assert r.status_code == 422 and r.json()["errors"]

    assert client.put("/api/characters/nobody", json=layla()).status_code == 404
    assert client.post("/api/validate", json={"x": 1}).json()["errors"]
    assert client.delete("/api/characters/nadia_saleh").status_code == 200
    assert client.get("/api/characters/nadia_saleh").status_code == 404


def test_page_and_static(client):
    assert "Patient simulator" in client.get("/").text
    for f in ("app.js", "session.js", "characters.js", "app.css"):
        assert client.get(f"/static/{f}").status_code == 200
    assert client.get("/config").json()["default_character"] == "tuning"


def test_ws_unknown_character_reports_error(client):
    with client.websocket_connect("/ws?character=nobody") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error" and "nobody" in msg["message"]


def test_editor_schema_covers_every_key():
    """Every leaf of the shipped file has a field in the editor."""
    js = (Path(__file__).parents[1] / "web" / "static" / "characters.js").read_text()

    def leaves(d, prefix=""):
        for k, v in d.items():
            p = f"{prefix}{k}"
            if isinstance(v, dict):
                yield from leaves(v, p + ".")
            else:
                yield p

    covered_by_widget = ("severity_scale.", "flag_deltas.")  # bands and flag widgets build these paths
    missing = [
        p for p in leaves(layla())
        if not p.startswith(covered_by_widget) and f'"{p}"' not in js and f"`{p}`" not in js
        and not p.startswith("audio_tags.")
    ]
    assert missing == []
    for flag in layla()["flag_deltas"]:
        assert f'name: "{flag}"' in js
