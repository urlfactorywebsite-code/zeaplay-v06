"""Loopback-only, stateless SDK HTTP with nonproduction broker capabilities."""

import ipaddress

from starlette.responses import JSONResponse


class BrokerOnlyHTTP:
    def __init__(self, app, broker):
        self.app, self.broker = app, broker

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope["headers"]}
        try:
            local = ipaddress.ip_address(scope["client"][0]).is_loopback
        except (ValueError, TypeError):
            local = False
        # Test transport is not browser OAuth: no cookies/CORS/Origin trust.
        if not local or b"origin" in headers:
            return await JSONResponse({"error": "Local test transport only"}, status_code=403)(scope, receive, send)
        capabilities = [v for k,v in scope["headers"] if k.lower() == b"x-zeaplay-test-broker"]
        if len(capabilities) != 1:
            return await JSONResponse({"error": "One fixture identity required"}, status_code=401)(scope, receive, send)
        capability = capabilities[0].decode("ascii", errors="replace")
        if self.broker.resolve(capability) is None:
            return await JSONResponse({"error": "Trusted fixture authentication required"}, status_code=401)(scope, receive, send)
        return await self.app(scope, receive, send)
