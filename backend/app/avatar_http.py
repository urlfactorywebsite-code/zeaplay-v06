"""HTTP boundaries shared by the existing avatar endpoints and asset mount."""

import re

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.staticfiles import StaticFiles

from .config import get_settings
from .media_http import sandbox_uploaded_response


class AvatarUploadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PATCH"} and (
                self.path.startswith(("/avatars", "/api/avatars"))
                or self.path.endswith("/avatar")
            ):
                size = get_settings().avatar_max_file_size_mb * 1024 * 1024
                limit = (
                    size + 65536
                    if request.headers.get("content-type", "").startswith("multipart/")
                    else ((size + 2) // 3) * 4 + 65536
                )
                consumed = 0
                receive = request.receive

                async def limited_receive():
                    nonlocal consumed
                    message = await receive()
                    consumed += len(message.get("body", b""))
                    if consumed > limit:
                        raise HTTPException(
                            status_code=413,
                            detail="Avatar request exceeds the size limit",
                        )
                    return message

                request = Request(request.scope, limited_receive)
            return await handler(request)

        return bounded


class AvatarSafeStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Uploaded legacy portraits are served through authenticated avatar routes.
        # Only the ten packaged SVG illustrations are public avatar assets.
        normalized = path.replace("\\", "/")
        if normalized.startswith("avatars/") and not re.fullmatch(
            r"avatars/library/default-avatar-(?:0[1-9]|10)\.svg", normalized
        ):
            raise HTTPException(status_code=404, detail="Not found")
        response = await super().get_response(path, scope)
        if normalized.startswith("task_templates/"):
            return sandbox_uploaded_response(response)
        return response
