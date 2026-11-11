"""Reject oversized uploads before multipart parsing can spool them to disk."""

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from . import service


class BackupRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            if not request.url.path.endswith("/imports/validate"):
                return await original(request)
            # Allow bounded multipart metadata in addition to the file limit.
            limit = service.MAX_UPLOAD + 1024**2
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    declared = int(length)
                except ValueError as exc:
                    raise HTTPException(400, "Invalid upload length.") from exc
                if declared < 0 or declared > limit:
                    raise HTTPException(
                        413, "Backup upload exceeds the request size limit."
                    )
            received = 0

            async def bounded_receive():
                nonlocal received
                message = await request.receive()
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(
                        413, "Backup upload exceeds the request size limit."
                    )
                return message

            return await original(Request(request.scope, receive=bounded_receive))

        return handle
