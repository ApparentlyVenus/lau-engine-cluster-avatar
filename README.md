# lau-engine-cluster-avatar

Backend for the cluster avatar: the simulated patient's ears, brain and voice.

```
mic -> VAD -> Riva STT -> turn end -> timing -> merger -> interpreter (Claude) -> state engine (rules)
    -> renderer (Claude, speculative) -> ElevenLabs -> speakers
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env      # fill in the three API keys
```

## Run

| Command | What it does |
|---|---|
| `python src/run.py web` | The web app at http://localhost:7860: pick a patient and talk, or create and edit patients. Works in the devcontainer (VSCode forwards the port). Use headphones. |
| `python src/run.py mic` | Local mic and speakers via PyAudio. Run on your own machine, not in Docker. |
| `python src/run.py wav clips/a.wav clips/b.wav` | Recorded clips through the full pipeline; replies saved to `out/`, latency measured to her first audio. |
| `python src/run.py text` | Type the doctor's lines. No audio. |

Useful options: `--no-tts`, `--tts-model eleven_flash_v2_5`, `--hold 0.8`, `--smart`, `--no-barge-in`, `--no-word-times`. See `python src/run.py --help`.

## Characters

Each patient is one tuning file in `src/state_engine/tuning/` (Layla is `tuning.json`). The **Characters** tab of the web app edits every field of these files: scenario, voice (with a play button to hear it), starting state, defenses, reactions to each flagged behaviour, escalation, when she cuts the doctor off, audio tags, trust and saturation bands, and turn timing. It validates as you edit and will not save an invalid file. New patients start as a copy of the selected one; deleted ones move to `deleted/`.

A session loads its character from disk when it starts, so edits apply to the next session without a restart. `--persona` picks the patient selected when the page opens; `--characters DIR` points the app at another folder.

Check a file from the command line: `python -m state_engine.validate state_engine/tuning/tuning.json` (from `src/`).

## Voice

Each patient's voice is in her tuning file, not `.env`:

```json
"voice": {
  "voice_id": "paste from ElevenLabs > Voices > voice menu > Copy voice ID",
  "model": "eleven_v3_conversational",
  "stability": 0.5
}
```

`model` and `stability` are optional. `--tts-model` overrides the model for a single run.

- `eleven_v3_conversational` (default) performs the audio tags. It goes through ElevenLabs' Text-to-Dialogue WebSocket, which must be enabled for the workspace.
- `eleven_flash_v2_5` is the fastest option. Tags are stripped and `[pause]` becomes `...`.

## Timing

Riva word timestamps give pauses inside the learner's turn, speaking rate and fillers. Pipeline events give the gap after her line and whether the learner talked over her. Claude receives these as measured text (`I'm sorry [pause 1.8s] this is hard`) and uses them for `silence_tolerance`. Talking over her sets `interruption` directly, without Claude. Thresholds are in the `timing` section of the tuning file.

## Tests

```
python -m pytest
```
