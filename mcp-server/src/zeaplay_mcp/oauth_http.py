"""OAuth resource transport; numeric loopback and a separate delegation plane."""
from contextvars import ContextVar
import ipaddress
import json
from pathlib import Path
import re

import anyio
import httpx2 as httpx
from starlette.responses import JSONResponse

from .auth import AuthorizationContext
from .request_identity import CredentialBinding
from .rest import BackendClient, loopback_origin


class OAuthTransport:
    def __init__(self, config):
        if config.get('mode') != 'isolated-oauth' or len(config.get('service_secret', '')) < 43:
            raise ValueError('Explicit isolated OAuth configuration required')
        self.backend_origin = loopback_origin(config['backend_origin'])
        self.origin = loopback_origin(config['resource_origin'])
        self.frontend = loopback_origin(config['frontend_origin'])
        self.service_secret = config['service_secret']
        self.binding = ContextVar('mcp_oauth_binding', default=None)
        self.limiter = anyio.CapacityLimiter(16)
        self.control = httpx.AsyncClient(timeout=httpx.Timeout(5), trust_env=False,
            follow_redirects=False, limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))
        self.backend = BackendClient(self.backend_origin)
        self.app = None

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    async def close(self):
        await self.control.aclose()
        await self.backend.close()

    async def authority(self, token, tool):
        path = '/mcp-oauth/delegate' if tool else '/mcp-oauth/validate'
        async with self.control.stream('POST', self.backend_origin + path,
            headers={'X-MCP-Service': self.service_secret, 'Cookie': '', 'Accept-Encoding': 'identity'},
            json={'token': token, 'tool_id': tool}) as response:
            if response.status_code != 200:
                return response.status_code, None
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 32768:
                    raise ValueError('Control response limit')
            value = json.loads(raw)
        if (not isinstance(value, dict) or not isinstance(value.get('tools'), list)
                or not set(value['tools']) <= {'zeaplay_list_tasks', 'zeaplay_get_task',
                    'zeaplay_list_overdue_tasks', 'zeaplay_list_subtasks', 'zeaplay_get_workload_summary'}):
            raise ValueError('Invalid authority response')
        if tool and (not isinstance(value.get('credential'), str)
                or not re.fullmatch(r'mcp_dt\.[A-Za-z0-9_-]{43}', value['credential'])
                or value['credential'] == token):
            raise ValueError('Invalid downstream credential')
        context = AuthorizationContext(user_id=value['user_id'], tenant_id=value['tenant_id'],
            client_id=value['client_id'], grant_id=value['grant_id'], scopes=frozenset(value['scopes']),
            role=value['role'], department_id=value['department_id'], policy_revision=value['policy_revision'])
        binding = CredentialBinding(context, value.get('credential', ''), allowed_tools=frozenset(value['tools']))
        return 200, binding

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def reject(status, code):
            header = {'Cache-Control': 'no-store'}
            if status in (401, 403):
                header['WWW-Authenticate'] = ('Bearer resource_metadata="' + self.origin +
                    '/.well-known/oauth-protected-resource/mcp", scope="tasks:read workload:read"' +
                    (', error="insufficient_scope"' if status == 403 else ''))
            return await JSONResponse({'error': code}, status_code=status, headers=header)(scope, receive, send)
        pairs = [(key.lower(), value) for key, value in scope['headers']]
        headers = dict(pairs)
        try:
            local = ipaddress.ip_address(scope['client'][0]).is_loopback
        except (ValueError, TypeError):
            local = False
        expected_host = self.origin.removeprefix('http://').encode()
        if (not local or headers.get(b'host') != expected_host or len([1 for key, _ in pairs if key == b'host']) != 1
                or len([1 for key, _ in pairs if key == b'origin']) > 1
                or headers.get(b'origin') not in (None, self.frontend.encode(), self.origin.encode())):
            return await reject(403, 'invalid_origin')
        if scope['path'] in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp'):
            return await JSONResponse({'resource': self.origin + '/mcp',
                'authorization_servers': [self.backend_origin + '/mcp-oauth'],
                'scopes_supported': ['tasks:read', 'workload:read'], 'bearer_methods_supported': ['header']},
                headers={'Cache-Control': 'no-store'})(scope, receive, send)
        if scope['path'] != '/mcp' or scope.get('query_string'):
            return await reject(400, 'invalid_request')
        credentials = [value for key, value in pairs if key == b'authorization']
        if len(credentials) != 1 or not credentials[0].lower().startswith(b'bearer '):
            return await reject(401, 'invalid_token')
        try:
            token = credentials[0][7:].decode('ascii')
            if len(token) > 128:
                return await reject(401, 'invalid_token')
        except UnicodeError:
            return await reject(401, 'invalid_token')
        try:
            self.limiter.acquire_nowait()
        except anyio.WouldBlock:
            return await reject(429, 'concurrency_limit')
        marker = None
        try:
            body = bytearray()
            with anyio.fail_after(10):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body.extend(message.get('body', b''))
                    if len(body) > 32768:
                        return await reject(413, 'request_too_large')
                    if not message.get('more_body', False):
                        break
            tool = None
            if body:
                def unique(pairs):
                    result = dict(pairs)
                    if len(result) != len(pairs): raise ValueError('Duplicate fields')
                    return result
                payload = json.loads(body, object_pairs_hook=unique)
                if not isinstance(payload, dict):
                    return await reject(400, 'invalid_request')
                if payload.get('method') == 'tools/call':
                    params = payload.get('params')
                    tool = params.get('name') if isinstance(params, dict) else None
                    if not isinstance(tool, str):
                        return await reject(400, 'invalid_request')
            status, binding = await self.authority(token, tool)
            if status != 200:
                return await reject(403 if status == 403 else 401 if status == 401 else 503, 'authorization_denied')
            marker = self.binding.set(binding)
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()
            return await self.app(scope, replay, send)
        except (ValueError, KeyError, TypeError, RecursionError):
            return await reject(400, 'invalid_request')
        except httpx.HTTPError:
            return await reject(503, 'authority_unavailable')
        except TimeoutError:
            return await reject(408, 'request_timeout')
        finally:
            if marker is not None:
                self.binding.reset(marker)
            self.limiter.release()
