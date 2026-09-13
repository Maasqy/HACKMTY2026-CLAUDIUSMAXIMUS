"""
src/detectors/

Deterministic, rule-based fraud signals — see rules.py for each detector and
signals.py for the Signal/Exhibit shapes they emit. Pure functions over
src.tools.EstateDB only: no SQL, no LLM, no randomness, no import of eval/
or the evaluation answer key.
"""

from . import rules
from .signals import SCHEME_TYPES, SOURCE_TABLES, Exhibit, Signal

__all__ = ["rules", "Signal", "Exhibit", "SCHEME_TYPES", "SOURCE_TABLES"]
