"""Live network check of the exit-verification path. Skipped unless
WATCH_PROXY_URL is set (never in CI). Run locally to confirm a real proxy
routes and geolocates as claimed:

    WATCH_PROXY_URL='http://user:pass_country-us_state-florida@geo.iproyal.com:12321' \\
      WATCH_PROXY_STATE=FL python -m pytest tests/test_core/test_watch_exit_verify_live.py -v
"""

from __future__ import annotations

import os

import pytest

import core.watch_observe as wo

_URL = os.environ.get("WATCH_PROXY_URL")
_STATE = os.environ.get("WATCH_PROXY_STATE", "FL")

pytestmark = pytest.mark.skipif(not _URL, reason="set WATCH_PROXY_URL to run the live proxy check")


@pytest.mark.asyncio
async def test_real_exit_verifies_in_the_expected_state() -> None:
    ok, url, detail = await wo.verify_exit_state(_URL, _STATE)
    assert ok, f"exit did not verify in {_STATE}: {detail}"
    assert detail["ip"] and detail["state_code"] == _STATE.upper()
    assert "_session-" in url
