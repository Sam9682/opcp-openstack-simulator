"""Custom exception hierarchy for the OpenStack Simulator."""


class SimulatorError(Exception):
    """Base exception for all simulator errors."""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(self.message)


class AuthenticationError(SimulatorError):
    """Raised when authentication fails (empty credentials)."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class TokenExpiredError(SimulatorError):
    """Raised when validating an expired token."""

    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)


class ResourceLimitExceededError(SimulatorError):
    """Raised when a resource creation exceeds the configured quota."""

    def __init__(self, message: str = "Resource limit exceeded"):
        super().__init__(message)


class DuplicateResourceError(SimulatorError):
    """Raised when creating a resource with a name that already exists."""

    def __init__(self, message: str = "Resource already exists"):
        super().__init__(message)


class ResourceNotFoundError(SimulatorError):
    """Raised when referencing a resource that does not exist."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class InvalidStateError(SimulatorError):
    """Raised when an operation is invalid for the resource's current state."""

    def __init__(self, message: str = "Invalid state for this operation"):
        super().__init__(message)
