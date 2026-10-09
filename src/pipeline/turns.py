from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_start.vad_user_turn_start_strategy import (
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.turns.user_turn_strategies import UserTurnStrategies

DEFAULT_HOLD_S = 0.6


def build_turn_processor(
    hold_s: float = DEFAULT_HOLD_S, smart: bool = False, barge_in: bool = False
) -> UserTurnProcessor:
    """barge_in: when the learner starts talking, stop her audio and cancel any
    reply in progress. Off for file runs (nothing is playing); on for live mic."""
    if smart:
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
            LocalSmartTurnAnalyzerV3,
        )
        from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
            TurnAnalyzerUserTurnStopStrategy,
        )

        stop = TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())
    else:
        stop = SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=hold_s)

    strategies = UserTurnStrategies(
        start=[
            VADUserTurnStartStrategy(enable_interruptions=barge_in),
            TranscriptionUserTurnStartStrategy(enable_interruptions=False),
        ],
        stop=[stop],
    )
    return UserTurnProcessor(user_turn_strategies=strategies)