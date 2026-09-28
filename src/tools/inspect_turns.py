import importlib
import inspect
import pkgutil
import re

import pipecat
from pipecat.transports.base_transport import TransportParams

for name in (
    "pipecat.turns.user_turn_processor",
    "pipecat.turns.user_turn_controller",
    "pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy",
    "pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy",
):
    src = inspect.getsource(importlib.import_module(name))
    print("=" * 70)
    print(name)
    print("frames:", sorted(set(re.findall(r"\b\w+Frame\b", src))))
    print("events:", sorted(set(re.findall(r"\bon_\w+", src))))

print("=" * 70)
print("TransportParams fields:")
fields = getattr(TransportParams, "model_fields", None) or getattr(TransportParams, "__dataclass_fields__", {})
print(sorted(fields))

print("=" * 70)
print("vad modules:")
print([m.name for m in pkgutil.walk_packages(pipecat.__path__, "pipecat.") if "vad" in m.name])