"""Integration aliases for the internal direct HTTP client."""
from .client import ThinQApi, ThinQAPIErrorCodes
AUTH_ERROR_CODES = frozenset({ThinQAPIErrorCodes.INVALID_TOKEN,
    ThinQAPIErrorCodes.INVALID_TOKEN_AGAIN, ThinQAPIErrorCodes.NOT_FOUND_TOKEN})
ThinQGuardedApi = ThinQApi
