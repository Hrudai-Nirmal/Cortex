"""Domain errors that preserve failure meaning across API and worker boundaries."""


class CortexError(Exception):
    """Base class for expected Cortex domain failures."""


class InputValidationError(CortexError):
    """Raised when a caller violates a domain entry contract."""


class HardwareAccelerationError(CortexError):
    """Raised when a strict worker profile cannot bind its required accelerator."""


class AuthorizationScopeError(CortexError):
    """Raised when retrieval is attempted without a complete access scope."""


class PipelineValidationError(CortexError):
    """Raised when a pipeline omits mandatory capabilities or has invalid edges."""


class ProviderOperationError(CortexError):
    """Raised when an external model or parser provider fails."""
