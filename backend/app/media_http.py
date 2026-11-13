"""Keep uploaded documents separate from executable application content."""

from starlette.responses import Response
from starlette.staticfiles import StaticFiles


def sandbox_uploaded_response(response: Response) -> Response:
    # Uploads can include SVG documents. A direct navigation must not let their
    # scripts run with the SPA origin or read its credentials. Keep anonymous
    # visibility, image embedding, range requests and downloads unchanged.
    response.headers.append("Content-Security-Policy", "sandbox allow-downloads")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class UploadedMediaStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        return sandbox_uploaded_response(await super().get_response(path, scope))
