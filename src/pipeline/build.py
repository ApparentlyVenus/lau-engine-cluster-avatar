"""One pipeline, used by every run mode (browser mic, local mic, wav files).

    input -> VAD -> Riva STT -> turn end -> timing -> merger
          -> interrupt watcher -> interpreter -> renderer -> TTS -> output
"""

import os
from dataclasses import dataclass

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.nvidia.stt import NvidiaSTTService

import tracing
from pipeline.processors import (
    InterpreterProcessor,
    InterruptWatcherProcessor,
    RendererProcessor,
    TimingTracker,
)
from pipeline.timing import TimingConfig
from pipeline.turn_gate import TurnGate
from pipeline.turn_merger import TurnMerger
from pipeline.turns import DEFAULT_HOLD_S, build_turn_processor
from state_engine.config import PersonaConfig
from tracing import mark


@dataclass
class SessionOptions:
    hold_s: float = float(os.environ.get("USER_SPEECH_TIMEOUT", DEFAULT_HOLD_S))
    smart_turn: bool = os.environ.get("TURN_STOP", "timer") == "smart"
    barge_in: bool = True
    tts: bool = True
    tts_model: str | None = None
    word_times: bool = os.environ.get("STT_WORD_TIMES", "1") != "0"


@dataclass
class Session:
    worker: PipelineWorker
    interpreter: InterpreterProcessor
    renderer: RendererProcessor


# Words this conversation is likely to contain, boosted in Riva's language
# model so "biopsy" stops coming back as "babes" or "bipolar". Whether the
# hosted streaming model honours boosting is up to NVIDIA; it is harmless if not.
CLINICAL_WORDS = [
    "biopsy", "results", "pathology", "pathologist", "oncologist", "oncology", "tumor", "tumour",
    "malignant", "benign", "cancer", "cancerous", "carcinoma", "lymphoma", "metastasis", "metastatic",
    "lymph", "node", "nodes", "mass", "lump", "scan", "MRI", "CT", "PET", "ultrasound", "mammogram",
    "chemotherapy", "chemo", "radiotherapy", "radiation", "surgery", "surgeon", "treatment", "prognosis",
    "diagnosis", "stage", "specialist", "referral", "appointment", "misheard", "sorry",
]
BOOST_SCORE = float(os.environ.get("STT_BOOST_SCORE", "4.0"))


def boosted_words(persona: PersonaConfig | None) -> list[str]:
    words = list(CLINICAL_WORDS)
    if persona is not None:
        # Her name, so "Mrs. Haddad" is heard as such.
        words += [w for w in persona.scenario.patient_name.replace(".", " ").split() if len(w) > 2]
    return words


def build_stt(word_times: bool, persona: PersonaConfig | None = None) -> NvidiaSTTService:
    # Default streaming model (nemotron-asr-streaming). parakeet-tdt-0.6b-v2
    # is rejected by the hosted endpoint in streaming mode.
    return NvidiaSTTService(
        api_key=os.environ["NVIDIA_API_KEY"],
        settings=NvidiaSTTService.Settings(
            word_time_offsets=word_times,
            boosted_lm_words=boosted_words(persona),
            boosted_lm_score=BOOST_SCORE,
        ),
    )


def build_session(
    persona_path: str,
    opts: SessionOptions,
    input_proc: FrameProcessor | None = None,
    output_proc: FrameProcessor | None = None,
    probes: dict[str, list[FrameProcessor]] | None = None,
) -> Session:
    """probes: extra processors to insert after a named stage
    ("vad", "stt", "turns", "renderer", "tts"), used by wav mode for logging."""
    probes = probes or {}
    persona = PersonaConfig.from_file(persona_path)
    timing_cfg = TimingConfig.from_tuning_file(persona_path)

    gate = TurnGate(timing_cfg.commit_after_s, timing_cfg.commit_after_unfinished_s)
    tracker = TimingTracker(timing_cfg, gate=gate)
    merger = TurnMerger(on_event=lambda event, detail="": mark("merger", event, detail), gate=gate)
    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    interpreter = InterpreterProcessor(
        persona,
        filler_getter=lambda: interrupt_watcher.filler_line_this_turn,
        timing_tracker=tracker,
        timing_cfg=timing_cfg,
        gate=gate,
    )
    voice = None
    voice_settings = None
    if opts.tts:
        from pipeline.tts import VoiceConfig, speech_settings
        voice = VoiceConfig.from_tuning_file(persona_path)
        voice_settings = speech_settings(voice, opts.tts_model)
    renderer = RendererProcessor(persona, gate=gate, voice_settings=voice_settings)
    gate.on_reopen += [interpreter.rollback, renderer.cancel_turn]

    stages: list[tuple[str, list[FrameProcessor]]] = [
        ("input", [input_proc] if input_proc else []),
        ("vad", [VADProcessor(vad_analyzer=SileroVADAnalyzer())]),
        ("stt", [build_stt(opts.word_times, persona)]),
        ("turns", [build_turn_processor(hold_s=opts.hold_s, smart=opts.smart_turn, barge_in=opts.barge_in)]),
        ("brain", [tracker, merger, interrupt_watcher, interpreter]),
        ("renderer", [renderer]),
    ]
    if opts.tts:
        from pipeline.tts import build_tts
        stages.append(("tts", build_tts(voice, opts.tts_model)))
    stages.append(("output", [output_proc] if output_proc else []))

    processors: list[FrameProcessor] = []
    for name, procs in stages:
        processors.extend(procs)
        processors.extend(probes.get(name, []))

    # With TTS the latency summary waits for her first audio.
    tracing.AUDIO_STAGE = opts.tts

    worker = PipelineWorker(
        Pipeline(processors),
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
        enable_rtvi=False,
        idle_timeout_secs=None,  # a learner may sit in silence for a long time
    )
    mark(
        "session",
        "pipeline built",
        f"hold={opts.hold_s}s smart={opts.smart_turn} barge_in={opts.barge_in} "
        f"tts={'on' if opts.tts else 'off'} word_times={opts.word_times}",
    )
    return Session(worker=worker, interpreter=interpreter, renderer=renderer)
