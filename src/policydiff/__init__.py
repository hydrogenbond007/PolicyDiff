"""Evidence-aware local comparison; execution is a separate opt-in CLI path."""

from ._version import __version__

from .engine import compare
from .catalogue import list_tasks
from .contract import describe_contract_change
from .log_inspection import inspect_log
from .schema import EvidenceError

__all__ = ["compare", "describe_contract_change", "inspect_log", "list_tasks", "EvidenceError", "__version__"]
