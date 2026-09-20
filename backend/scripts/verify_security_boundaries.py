"""Offline regression checks: revoked sessions and untrusted CSP payloads."""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('PUBLIC_DATA_API_KEY', 'verify-only')
from app.api import auth_deps, csp_report


async def main():
    identity = SimpleNamespace(user_id=1, epoch=3)
    auth = SimpleNamespace(enabled=True, cookie_name='session', verify_token=lambda _: identity)
    async def read(_):
        return {'id': 1, 'session_epoch': 4}
    with patch.object(auth_deps, 'get_user_auth', return_value=auth), patch.object(auth_deps, 'get_database', return_value=SimpleNamespace(aread=read)):
        request = SimpleNamespace(cookies={'session': 'old'})
        assert await auth_deps.optional_identity(request) is None
        try:
            await auth_deps.require_login(request)
            raise AssertionError('revoked token accepted')
        except auth_deps.HTTPException as exc:
            assert exc.status_code == 401
        identity.epoch = 4
        assert await auth_deps.optional_identity(request) is identity
    for value in [None, 1, 'x', [], {'effective-directive': '   '}]:
        assert csp_report.record(value) is None
    csp_report.reset()
    async def stream():
        yield json.dumps([{'body': 'not-an-object'}, {'body': {'effectiveDirective': 'script-src', 'blockedURL': 'https://example.com/path?secret=1'}}]).encode()
    response = await csp_report.csp_report(SimpleNamespace(stream=stream))
    assert response.status_code == 204
    assert csp_report.snapshot()['total'] == 1
    assert 'secret' not in str(csp_report.snapshot())
    consumed = []
    async def oversized():
        consumed.append(1)
        yield b'x' * 8193
        consumed.append(2)
        raise AssertionError('oversized stream consumed beyond limit')
    assert (await csp_report.csp_report(SimpleNamespace(stream=oversized))).status_code == 204
    assert consumed == [1]
    print('PASS: revoked/current sessions, malformed CSP, whitespace, host-only aggregation, stream limit')

asyncio.run(main())
