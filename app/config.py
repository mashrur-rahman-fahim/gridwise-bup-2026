"""Runtime configuration. Values come from the environment only - never from source."""
import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
PORT = int(os.environ.get("PORT", "8000"))

# Per-call ceiling for one LLM request. Two attempts must fit inside the
# 30 s per-request budget with room for the solver and serialization.
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "9"))

# Judge tolerance is 0.01 kWh / 0.01 BDT. We publish at 1e-6 and stay far inside it.
TOL = 0.01
ROUND_DP = 6
