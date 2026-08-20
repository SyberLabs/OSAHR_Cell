"""Exception hierarchy for OSAHR."""

from __future__ import annotations


class OSAHRError(Exception):
    """Base class for all kernel errors."""


class SchemaError(OSAHRError):
    """Raised when a schema is invalid."""


class ValidationError(OSAHRError):
    """Raised when a graph or mutation violates an invariant."""


class PatternError(OSAHRError):
    """Raised when a pattern or rule is malformed."""


class MatchError(OSAHRError):
    """Raised when an invalid match is applied."""


class RewriteError(OSAHRError):
    """Raised when a rewrite transaction fails."""


class HazardError(OSAHRError):
    """Raised when a hazard is negative or non-finite."""


class ReplayError(OSAHRError):
    """Raised when replay diverges from the event log."""


class ResourceLimitError(OSAHRError):
    """Raised when a configured runtime resource limit is exceeded."""


class ExpressionError(OSAHRError):
    """Raised when a safe expression fails to compile or evaluate."""


class HazardBoundError(HazardError):
    """A declared thinning bound failed to dominate an actual hazard."""


class SchedulerError(OSAHRError):
    """Stochastic scheduler state or contract failure."""


class AdaptationError(OSAHRError):
    """Adaptive parameter constraint failure."""


class MetaRewriteError(OSAHRError):
    """Safe meta-rule instantiation or repertoire update failure."""
