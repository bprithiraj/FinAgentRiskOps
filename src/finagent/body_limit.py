from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    """Bound actual consumed bytes, including chunked bodies and misleading headers."""

    def __init__(self, app, limit=32768):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            total += len(data)
            if total > self.limit:
                response = JSONResponse(
                    {"error": "Request exceeds 32 KiB."},
                    status_code=413,
                    headers={"Cache-Control": "no-store"},
                )
                return await response(scope, receive, send)
            chunks.append(data)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
