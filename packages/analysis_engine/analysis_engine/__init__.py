"""FlightPath analysis engine (M5): rule-based detectors with event citations."""

from analysis_engine.detectors import CATEGORIES, DETECTOR_VERSION, Finding, analyze

__all__ = ["CATEGORIES", "DETECTOR_VERSION", "Finding", "analyze"]
__version__ = "0.5.0"
