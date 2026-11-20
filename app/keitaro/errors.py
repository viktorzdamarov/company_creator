"""Typed errors raised by the Keitaro client. API routes map them to HTTP responses."""


class KeitaroError(Exception):
    """Base error for any Keitaro API failure."""

    http_status = 502  # status Adrobot returns to its own clients

    def __init__(
        self, message: str, *, status_code: int | None = None, path: str | None = None, detail: str | None = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.path = path
        self.detail = detail  # Keitaro's own error text, if any

    def __str__(self) -> str:
        where = f" [{self.status_code} {self.path}]" if self.status_code else ""
        return f"{self.message}{where}"


class KeitaroAuthError(KeitaroError):
    """401: Keitaro did not accept the API key (wrong or revoked). Missing permissions are KeitaroForbiddenError."""

    http_status = 502


class KeitaroForbiddenError(KeitaroAuthError):
    """403: the API key is valid but its role has no permission for this section (e.g. Offers)."""

    http_status = 403


class KeitaroNotFoundError(KeitaroError):
    """404: entity does not exist (or is not visible to this API key)."""

    http_status = 404


class KeitaroValidationError(KeitaroError):
    """400/422: Keitaro rejected the payload."""

    http_status = 422


class KeitaroRateLimitError(KeitaroError):
    """429 after all retries."""

    http_status = 503


class KeitaroTimeoutError(KeitaroError):
    """Network timeout after all retries."""

    http_status = 504


class KeitaroUnavailableError(KeitaroError):
    """5xx or connection error after all retries."""

    http_status = 503
