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


def build_stt(word_times: bool) -> NvidiaSTTService:
    # Default streaming model (nemotron-asr-streaming). parakeet-tdt-0.6b-v2
    # is rejected by the hosted endpoint in streaming mode.
    return NvidiaSTTService(
        api_key=os.environ["NVIDIA_API_KEY"],
        settings=NvidiaSTTService.Settings(word_time_offsets=word_times),
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

    tracker = TimingTracker(timing_cfg)
    merger = TurnMerger(on_event=lambda event, detail="": mark("merger", event, detail))
    interrupt_watcher = InterruptWatcherProcessor(persona, state_getter=lambda: interpreter.state)
    interpreter = InterpreterProcessor(
        persona,
        filler_getter=lambda: interrupt_watcher.filler_line_this_turn,
        timing_tracker=tracker,
        timing_cfg=timing_cfg,
    )
    renderer = RendererProcessor(persona)

    stages: list[tuple[str, list[FrameProcessor]]] = [
        ("input", [input_proc] if input_proc else []),
        ("vad", [VADProcessor(vad_analyzer=SileroVADAnalyzer())]),
        ("stt", [build_stt(opts.word_times)]),
        ("turns", [build_turn_processor(hold_s=opts.hold_s, smart=opts.smart_turn, barge_in=opts.barge_in)]),
        ("brain", [tracker, merger, interrupt_watcher, interpreter]),
        ("renderer", [renderer]),
    ]
    if opts.tts:
        from pipeline.tts import VoiceConfig, build_tts
        stages.append(("tts", build_tts(VoiceConfig.from_tuning_file(persona_path), opts.tts_model)))
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
