"""Offline stdio or isolated REST over stdio/loopback HTTP; no public transport."""

import argparse
import json
import logging
from pathlib import Path

import anyio
from mcp.server.stdio import stdio_server

from .auth import FixtureAuthorization
from .config import Settings
from .errors import SafeError
from .fixtures import identity
from .security import configure_logging, install_offline_guard
from .server import create_server

logger = logging.getLogger("zeaplay_mcp")


async def serve(settings: Settings) -> None:
    install_offline_guard()
    server = create_server(settings)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def serve_rest(settings: Settings, args) -> None:
    from .local_http import BrokerOnlyHTTP
    from .request_identity import RequestAuthorization
    from .rest import AuthenticatedRestAdapter
    from .test_broker import TrustedTestBroker

    broker = TrustedTestBroker.load(args.broker_config)
    try:
        await broker.start()
        authorization = RequestAuthorization()
        adapter = AuthenticatedRestAdapter(broker.backend, authorization)
        server = create_server(settings, authorization, adapter, broker.resolver(args.identity))
        if args.transport == "stdio":
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
        else:
            import uvicorn
            app = server.streamable_http_app(stateless_http=True, json_response=True,
                host="127.0.0.1", max_request_body_size=32768)
            config = uvicorn.Config(BrokerOnlyHTTP(app, broker), host="127.0.0.1",
                port=args.port, access_log=False, log_config=None, proxy_headers=False)
            await uvicorn.Server(config).serve()
    finally:
        await broker.close()


async def serve_oauth(settings: Settings, args) -> None:
    import uvicorn
    from .oauth_http import OAuthTransport
    from .request_identity import RequestAuthorization
    from .rest import AuthenticatedRestAdapter
    transport = OAuthTransport.load(args.oauth_config)
    try:
        authorization = RequestAuthorization()
        server = create_server(settings, authorization, AuthenticatedRestAdapter(transport.backend, authorization),
                               lambda ctx: transport.binding.get())
        transport.app = server.streamable_http_app(stateless_http=True, json_response=True,
            host='127.0.0.1', max_request_body_size=32768)
        config = uvicorn.Config(transport, host='127.0.0.1', port=args.port,
                                access_log=False, log_config=None, proxy_headers=False)
        await uvicorn.Server(config).serve()
    finally:
        await transport.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only ZeaPlay MCP: offline mock or isolated authenticated REST"
    )
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--mode", choices=["mock", "rest", "oauth"], default="mock")
    parser.add_argument('--oauth-config', type=Path)
    parser.add_argument("--isolated-test", action="store_true")
    parser.add_argument("--broker-config", type=Path)
    parser.add_argument("--identity", help="Trusted launch-only fixture alias for stdio")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Local liveness/readiness JSON; no listener",
    )
    args = parser.parse_args()
    configure_logging()
    if (args.mode == "rest" and (not args.isolated_test or args.broker_config is None or args.check)
            or args.mode == "mock" and (args.transport != "stdio" or args.broker_config is not None or args.isolated_test or args.identity is not None)
            or (args.mode == 'oauth' and (not args.isolated_test or args.transport != 'http' or not args.oauth_config or args.broker_config or args.identity or args.check))
            or (args.mode != 'oauth' and args.oauth_config is not None)
            or not 1 <= args.port <= 65535):
        logger.error({"event": "invalid_configuration", "ready": False})
        raise SystemExit(2)
    try:
        settings = Settings.from_environment()
    except (ValueError, TypeError):
        logger.error({"event": "invalid_configuration", "mock": True, "ready": False})
        raise SystemExit(2) from None
    if args.check:
        ready = True
        try:
            auth = FixtureAuthorization(identity(settings.fixture_identity))
            auth.require("tasks:read")
            auth.require("workload:read")
        except SafeError:
            ready = False
        print(
            json.dumps(
                {
                    "alive": True,
                    "ready": ready,
                    "mode": "mock",
                    "transport": "stdio",
                    "live_rest": False,
                }
            )
        )
        raise SystemExit(0 if ready else 3)
    try:
        if args.mode == "mock":
            anyio.run(serve, settings)
        elif args.mode == 'rest':
            anyio.run(serve_rest, settings, args)
        else:
            anyio.run(serve_oauth, settings, args)
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - Never expose an internal traceback over the CLI.
        logger.error({"event": "server_stopped", "mock": args.mode == "mock",
                      "outcome": getattr(exc, "code", type(exc).__name__)})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
