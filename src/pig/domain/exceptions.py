class DomainError(Exception):
    """Base exception for domain-level failures."""


class EntityNotFoundError(DomainError):
    """Raised when a requested domain entity does not exist."""


class InvariantViolationError(DomainError):
    """Raised before persistence when a domain invariant would be violated."""


class ConcurrentStateError(DomainError):
    """Raised when an expected current state no longer matches persistence."""
