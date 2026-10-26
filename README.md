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
| `python src/run.py web` | The web app at http://localhost:7860: pick a patient and talk to her, or create and edit patients. Works in the devcontainer (VSCode forwards the port). Use headphones. |
| `python src/run.py mic` | Local mic and speakers via PyAudio. Run on your own machine, not in Docker. |
| `python src/run.py wav clips/a.wav clips/b.wav` | Recorded clips through the full pipeline; her replies saved to `out/`, latency measured to her first audio. |
| `python src/run.py text` | Type the doctor's lines. No audio. |
| `python src/run.py check` | Live checks: prompt caching (token counts), Riva, ElevenLabs. |

Useful options: `--no-tts`, `--tts-model eleven_flash_v2_5`, `--hold 0.8`, `--smart`, `--no-barge-in`, `--no-word-times`. See `python src/run.py --help`.

## Characters

Each patient is one tuning file in `src/state_engine/tuning/` (Layla is `tuning.json`). The **Characters** tab of the web app edits every field of these files: scenario, voice (with a play button to hear it), starting state, defenses, reactions to each flagged behaviour, escalation, when she cuts the doctor off, audio tags, trust and saturation bands, and turn timing. It validates as you edit and will not save an invalid file. New patients start as a copy of the selected one; deleted ones move to `deleted/`.

A session loads its character from disk when it starts, so edits apply to the next session without a restart. `--persona` picks the patient selected when the page opens; `--characters DIR` points the app at another folder.

Check a file from the command line: `python -m state_engine.validate state_engine/tuning/tuning.json` (from `src/`).

## How she behaves

The interpreter (Claude) scores each learner turn and flags the turn that discloses the diagnosis. Rules then update trust, saturation, how she rates the doctor (competence) and shock. Before the news she stays near her starting state; the disclosure starts shock, which fades faster with validation and silence and slower with logistics and jargon. Her emotion and undertone are the two strongest of calm, shock, anger, grief, fear and bargaining, scored from those variables (formulas in `state_engine/config.py`, weights in the character's `arc` section). If trust stays at the walk-out level she ends the consultation and the session stops.

Each emotion has a speech profile (`speech` section): a pause before she answers, voice speed (Flash/Turbo only), stability, and a description of how she talks that the renderer follows. Both sections are optional and editable in the Characters tab; blank fields use the defaults.

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

## Deploy on Vercel (demo)

The app is one FastAPI app (`src/asgi.py`) with a WebSocket for audio, which Vercel's Python functions support.

1. Import the repo in Vercel (framework: FastAPI, auto-detected from `src/asgi.py`).
2. Environment variables: `ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`, `ELEVENLABS_API_KEY`, `APP_USERNAME`, `APP_PASSWORD` (optional `APP_SECRET`, `DEFAULT_CHARACTER`).
3. Deploy, open the URL, sign in.

What to know:
- **Session length.** A WebSocket closes when the function hits its max duration: 300 s on Hobby. On Pro, raise `maxDuration` in `vercel.json` to 800 (or up to 1800, beta) so a full conversation fits. The page says when the connection closed.
- **Characters are read-only** there (the filesystem is read-only). Edit locally, commit, redeploy; the editor still lets you try fields, play voices and export JSON.
- **Size.** The dependencies are about 450 MB, near the 500 MB Python limit; new projects allow larger functions automatically.
- **First start is slow** after a cold start (Pipecat and the voice-activity model load on the first session).
- **One person per tab.** Several people can talk at once, but the latency card is shared per server instance and can show another session's numbers.
- **Login**: one shared account from the environment, a signed cookie for 12 hours, no accounts or sign-up. Without `APP_USERNAME`/`APP_PASSWORD` there is no login (local use).

## Tests

```
python -m pytest
```
