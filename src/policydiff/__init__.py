"""Evidence-aware, local-only policy comparison. No robot or model execution."""

from ._version import __version__

from .engine import compare
from .schema import EvidenceError

__all__ = ["compare", "EvidenceError", "__version__"]
