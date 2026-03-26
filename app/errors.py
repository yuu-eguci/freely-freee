"""Application level error definitions."""


class AppError(Exception):
    """Base exception for application level errors."""


class ConfigError(AppError):
    """Raised when required configuration is missing or invalid."""


class TokenStoreError(AppError):
    """Raised when token.json cannot be read or written safely."""


class OAuthTokenError(AppError):
    """Raised when token endpoint communication fails."""


class MenuError(AppError):
    """Base exception for interactive menu errors."""


class MenuEnvironmentError(MenuError):
    """Raised when interactive menu cannot be shown in current terminal."""


class MenuInputError(MenuError):
    """Raised when menu input stream is invalid or interrupted unexpectedly."""


class MenuCancelled(MenuError):
    """Raised when user cancels menu explicitly."""


class ActionError(AppError):
    """Base exception for action execution errors."""


class ActionRegistrationError(ActionError):
    """Raised when action registry definitions are invalid."""


class UnknownActionError(ActionError):
    """Raised when an unknown action_id is requested."""


class ActionExecutionError(ActionError):
    """Raised when an action cannot complete successfully."""


class ApiClientError(AppError):
    """Base exception for API client failures."""


class ApiConnectionError(ApiClientError):
    """Raised when an API request cannot reach the server."""


class ApiResponseError(ApiClientError):
    """Raised when an API response is invalid or unsuccessful."""


class ApiAuthenticationError(ApiClientError):
    """Raised when an API request is rejected due to authentication."""
