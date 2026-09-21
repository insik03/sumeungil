import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.middleware.private_response import PrivateResponseMiddleware

async def check(path, status, private):
    messages = []
    async def app(scope, receive, send):
        await send({"type":"http.response.start", "status":status, "headers":[(b"Cache-Control", b"public, max-age=60"), (b"x-test",b"kept")]})
        await send({"type":"http.response.body", "body":b"synthetic"})
    async def receive():
        return {"type":"http.request", "body":b""}
    async def send(message):
        messages.append(message)
    await PrivateResponseMiddleware(app)({"type":"http", "path":path}, receive, send)
    headers = {k.lower(): v for k,v in messages[0]["headers"]}
    assert headers[b"cache-control"] == (b"private, no-store" if private else b"public, max-age=60")
    assert headers[b"x-test"] == b"kept" and messages[1]["body"] == b"synthetic"
for path in ("/api/v1/auth/me", "/api/v1/admin/users", "/api/v1/inquiries"):
    for status in (200, 401, 503):
        asyncio.run(check(path, status, True))
asyncio.run(check("/static/example.js",200,False))
print("PASS: API no-store on success/errors; static response unchanged")
