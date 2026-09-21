"""Keep dynamic API responses out of browser/shared HTTP caches."""
class PrivateResponseMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        async def private_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = [(k,v) for k,v in message.get("headers", []) if k.lower() != b"cache-control"]
                message["headers"] = headers + [(b"cache-control", b"private, no-store")]
            await send(message)
        await self.app(scope, receive, private_send)
