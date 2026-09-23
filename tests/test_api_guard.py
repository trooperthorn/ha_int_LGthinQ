"""Check that an empty-body unauthorized response stops before JSON parsing."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock


class FakeErrorCodes:
    INVALID_TOKEN = "1103"
    INVALID_TOKEN_AGAIN = "1218"
    NOT_FOUND_TOKEN = "1302"


class FakeApiException(Exception):
    def __init__(self, code, message, headers):
        self.code = code
        super().__init__(message)


class FakeApi:
    async def _async_fetch(self, method, url, **kwargs):
        return self.response


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sdk = types.ModuleType("thinqconnect")
        sdk.ThinQApi = FakeApi
        sdk.ThinQAPIErrorCodes = FakeErrorCodes
        sdk.ThinQAPIException = FakeApiException
        aiohttp = types.ModuleType("aiohttp")
        aiohttp.ClientResponse = object
        cls.old_sdk = sys.modules.get("thinqconnect")
        cls.old_aiohttp = sys.modules.get("aiohttp")
        sys.modules["thinqconnect"] = sdk
        sys.modules["aiohttp"] = aiohttp
        path = Path(__file__).parents[1] / "custom_components/lg_thinq_extended/api.py"
        spec = importlib.util.spec_from_file_location("lg_api_guard_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    @classmethod
    def tearDownClass(cls):
        for name, old in (("thinqconnect", cls.old_sdk), ("aiohttp", cls.old_aiohttp)):
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    def test_unauthorized_response_is_released_and_raised(self):
        api = self.module.ThinQGuardedApi()
        api.response = types.SimpleNamespace(status=401, release=Mock())
        with self.assertRaises(FakeApiException) as caught:
            asyncio.run(api._async_fetch("GET", "https://example.test/devices"))
        self.assertEqual(caught.exception.code, "1103")
        api.response.release.assert_called_once()

    def test_success_response_passes_through(self):
        api = self.module.ThinQGuardedApi()
        api.response = types.SimpleNamespace(status=200, release=lambda: None)
        self.assertIs(
            asyncio.run(api._async_fetch("GET", "https://example.test/devices")),
            api.response,
        )


if __name__ == "__main__":
    unittest.main()

