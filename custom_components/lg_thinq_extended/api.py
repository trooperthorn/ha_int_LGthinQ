"""ThinQ API wrapper for responses without LG's usual JSON error body."""

from typing import Any

from aiohttp import ClientResponse
from thinqconnect import ThinQApi, ThinQAPIErrorCodes, ThinQAPIException


AUTH_ERROR_CODES = frozenset(
    {
        ThinQAPIErrorCodes.INVALID_TOKEN,
        ThinQAPIErrorCodes.INVALID_TOKEN_AGAIN,
        ThinQAPIErrorCodes.NOT_FOUND_TOKEN,
    }
)


class ThinQGuardedApi(ThinQApi):
    """Map an empty-body 401 to an authentication error before JSON parsing.

    The pinned SDK parses every response as JSON before checking HTTP status.
    LG returned an empty-body 401 for an invalid PAT in the owner probe.
    """

    async def _async_fetch(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
        response = await super()._async_fetch(method, url, **kwargs)
        if response.status == 401:
            response.release()
            raise ThinQAPIException(
                code=ThinQAPIErrorCodes.INVALID_TOKEN,
                message="Unauthorized",
                headers={},
            )
        return response

