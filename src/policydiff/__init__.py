"""Evidence-aware, local-only policy comparison. No robot or model execution."""

from ._version import __version__

from .engine import compare
from .contract import describe_contract_change
from .log_inspection import inspect_log
from .schema import EvidenceError

__all__ = ["compare", "describe_contract_change", "inspect_log", "EvidenceError", "__version__"]
