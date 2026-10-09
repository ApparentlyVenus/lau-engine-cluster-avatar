# lau-engine-cluster-avatar

Backend for the cluster avatar: the simulated patient's ears, brain and voice.

```
mic -> VAD -> Riva STT -> turn end -> timing -> merger -> interpreter (Claude) -> state engine (rules)
    -> renderer (Claude, speculative) -> ElevenLabs -> speakers
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env      # fill in the four keys
```

## Run

| Command | What it does |
|---|---|
| `python src/run.py web` | Talk to her from the browser. Open http://localhost:7860. Works in the devcontainer (VSCode forwards the port). Use headphones. |
| `python src/run.py mic` | Local mic and speakers via PyAudio. Run on your own machine, not in Docker. |
| `python src/run.py wav clips/a.wav clips/b.wav` | Recorded clips through the full pipeline; her replies saved to `out/`, latency measured to her first audio. |
| `python src/run.py text` | Type the doctor's lines. No audio. |

Useful options: `--no-tts`, `--tts-model eleven_flash_v2_5`, `--hold 0.8`, `--smart`, `--no-barge-in`, `--no-word-times`. See `python src/run.py --help`.

## Voice

- `eleven_v3_conversational` (default) performs the audio tags. It goes through ElevenLabs' Text-to-Dialogue WebSocket, which must be enabled for the workspace.
- `eleven_flash_v2_5` is the fastest option. Tags are stripped and `[pause]` becomes `...`.

## Timing

Riva word timestamps give pauses inside the learner's turn, speaking rate and fillers. Pipeline events give the gap after her line and whether the learner talked over her. Claude receives these as measured text (`I'm sorry [pause 1.8s] this is hard`) and uses them for `silence_tolerance`. Talking over her sets `interruption` directly, without Claude. Thresholds are in the `timing` section of the tuning file.

## Tests

```
python -m pytest
```
