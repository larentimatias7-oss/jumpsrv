class JumpServerError(Exception):
    """Base JumpServer API error."""
    pass


class JumpServerAuthError(JumpServerError):
    """Authentication or signature failure (HTTP 401)."""
    pass


class JumpServerValidationError(JumpServerError):
    """Bad request payload or missing fields (HTTP 400)."""
    pass


class JumpServerNetworkError(JumpServerError):
    """Connection failure or timeout communicating with JumpServer."""
    def __init__(self, message: str, attempt: int = 1):
        super().__init__(message)
        self.attempt = attempt
