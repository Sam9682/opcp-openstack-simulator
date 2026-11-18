"""Custom exception hierarchy for the OpenStack Simulator."""

from typing import Any, Optional

from openstack_simulator import messages


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


class InvalidPatchError(SimulatorError):
    """Raised when a JSON Patch operation is malformed or unsupported."""

    def __init__(self, message: str = "Invalid JSON patch"):
        super().__init__(message)


class InvalidTimestamp(SimulatorError):
    """Raised when a virtual-clock timestamp cannot be parsed (HTTP 400)."""

    status_code = 400

    def __init__(self, message: str = "Invalid timestamp"):
        super().__init__(message)


class InvalidTrait(SimulatorError):
    """Raised when a trait name is malformed or neither CUSTOM_ nor standard (HTTP 400)."""

    status_code = 400

    def __init__(self, message: str = "Invalid trait"):
        super().__init__(message)


# ---------------------------------------------------------------------------
# Server-creation error model (server-creation-rules spec)
# ---------------------------------------------------------------------------


class SimError(Exception):
    """Base class for errors rendered as API envelopes.

    ``kind`` is the Compute envelope name (``badRequest``, ``itemNotFound``,
    ``forbidden``, ``computeFault``, ``conflictingRequest``) or ``ironic``
    for Baremetal errors.
    """

    status: int = 500
    kind: str = "computeFault"

    def __init__(
        self,
        status: Optional[int] = None,
        kind: Optional[str] = None,
        message: str = "",
        details: Any = None,
    ):
        if status is not None:
            self.status = status
        if kind is not None:
            self.kind = kind
        self.message = message
        self.details = details
        super().__init__(message)


class _Fixed(SimError):
    """SimError subclass with fixed status/kind; takes (message, details)."""

    def __init__(self, message: str = "", details: Any = None):
        super().__init__(self.status, self.kind, message, details)


class NoValidHost(_Fixed):
    status, kind = 500, "computeFault"

    def __init__(self, message: Optional[str] = None, details: Any = None):
        super().__init__(
            messages.no_valid_host() if message is None else message, details
        )


class InvalidAvailabilityZone(_Fixed):
    status, kind = 400, "badRequest"


class FlavorNotFound(_Fixed):
    status, kind = 400, "badRequest"


class FlavorNotAccessible(_Fixed):
    status, kind = 400, "badRequest"


class ImageNotFound(_Fixed):
    status, kind = 400, "badRequest"


class ImageNotActive(_Fixed):
    status, kind = 400, "badRequest"


class KeypairNotFound(_Fixed):
    status, kind = 400, "badRequest"


class SecurityGroupNotFound(_Fixed):
    status, kind = 400, "badRequest"


class BadRequest(_Fixed):
    status, kind = 400, "badRequest"


class InvalidTimestamp(_Fixed):
    status, kind = 400, "badRequest"


class InvalidTrait(_Fixed):
    status, kind = 400, "badRequest"


class NetworkNotFound(_Fixed):
    status, kind = 404, "itemNotFound"


class ServerNotFound(_Fixed):
    status, kind = 404, "itemNotFound"


class QuotaExceeded(_Fixed):
    status, kind = 403, "forbidden"


class Forbidden(_Fixed):
    status, kind = 403, "forbidden"


class InstanceLocked(_Fixed):
    status, kind = 409, "conflictingRequest"


class Conflict(_Fixed):
    status, kind = 409, "conflictingRequest"


# Ironic (Baremetal) errors


class NodeLocked(_Fixed):
    status, kind = 409, "ironic"


class NodeNotProvided(_Fixed):
    status, kind = 409, "ironic"


class InvalidState(_Fixed):
    status, kind = 409, "ironic"


class NotAuthorized(_Fixed):
    status, kind = 403, "ironic"


def render_error(err: SimError) -> dict:
    """Render a SimError as its JSON envelope body."""
    if err.kind == "ironic":
        return messages.ironic_envelope(err.message)
    return messages.compute_envelope(err.kind, err.message, err.status, err.details)
