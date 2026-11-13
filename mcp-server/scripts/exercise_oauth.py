"""Actual code/consent/token and MCP HTTP checks in the attested owned fixture."""
import asyncio
from contextlib import asynccontextmanager
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

NAMES = ('zeaplay_list_tasks', 'zeaplay_get_task', 'zeaplay_list_overdue_tasks',
         'zeaplay_list_subtasks', 'zeaplay_get_workload_summary')
checks = []


def check(name, condition):
    checks.append({'case': name, 'result': 'PASS' if condition else 'FAIL'})
    if not condition:
        raise RuntimeError(name)


def callback_query(uri, expected_state, expected_issuer):
    query = parse_qs(urlsplit(uri).query)
    if query.get('iss') != [expected_issuer] or len(query.get('state', [])) != 1 or not hmac.compare_digest(query['state'][0], expected_state):
        raise ValueError('OAuth callback authority mismatch')
    return query


async def exercise(root, origin):
    cfg = json.loads((root/'broker.json').read_text())
    cfg['oauth_service_secret'] = json.loads((root/'oauth.json').read_text())['service_secret']
    sensitive = {cfg['oauth_service_secret']}
    sensitive.add(cfg['attestation_secret'])
    sensitive.update(account[key] for account in cfg['accounts'].values() for key in ('password','capability'))
    fixture = json.loads((root/'fixtures.json').read_text())
    backend, resource = cfg['backend_origin'], origin + '/mcp'
    issuer = backend + '/mcp-oauth'
    redirect = backend + '/__phase4a__/callback'
    client_id = 'zea-local-client'
    async with httpx.AsyncClient(base_url=backend, trust_env=False, timeout=20, follow_redirects=False) as web:
        nonce = secrets.token_hex(32)
        attestation = (await web.get('/__phase2b__/attest', params={'nonce': nonce})).json()
        expected = hmac.new(cfg['attestation_secret'].encode(), (cfg['run_id']+':'+nonce).encode(), hashlib.sha256).hexdigest()
        check('owned backend attested before passwords', attestation['run_id'] == cfg['run_id'] and hmac.compare_digest(attestation['proof'], expected))

        def bearer(token): return {'Authorization': 'Bearer '+token}

        async def login(alias):
            account = cfg['accounts'][alias]
            response = await web.post('/auth/login', json={'email': account['email'], 'password': account['password']})
            check('real existing login '+alias, response.status_code == 200)
            sensitive.update(response.json()['token'][key] for key in ('access_token', 'refresh_token'))
            return response.json()['token']['access_token']

        async def mutate(action, **kw):
            response = await web.post('/__phase4a__/mutate', headers={'X-Fixture-Control': cfg['attestation_secret']}, json={'action': action, **kw})
            check('owned mutation '+action, response.status_code == 200)

        owner = await login('a-owner')

        async def snapshot(token=owner):
            response = await web.get('/mcp-management', headers=bearer(token))
            check('management authenticated snapshot', response.status_code == 200)
            return response.json()

        async def policy(token=owner, **changes):
            current = (await snapshot(token))['configuration']
            value = dict(enabled=True, read_only=True, allowed_tool_ids=list(NAMES),
                         allowed_roles=['owner', 'admin', 'manager', 'user'], reason='Isolated verification', expected_revision=current['revision'])
            value.update(changes)
            response = await web.patch('/mcp-management/policy', headers=bearer(token), json=value)
            check('durable tenant policy accepted', response.status_code == 200 and response.json()['remote_access_enabled'] is False)
            return value

        await policy()
        # A separate tenant's actual owner context must save its own policy.
        await mutate('role', alias='b-member', value='owner')
        await policy(await login('b-member'))
        await mutate('role', alias='b-member', value='user')
        users = {alias: await login(alias) for alias in ('a-member', 'b-member', 'a-peer')}
        check('ordinary user cannot manage', (await web.get('/mcp-management', headers=bearer(users['a-member']))).status_code == 403)
        before = await snapshot()
        denied_policy = dict(enabled=True, read_only=True, allowed_tool_ids=list(NAMES), allowed_roles=['user'], reason='Isolated denial', expected_revision=before['configuration']['revision'])
        check('ordinary user policy write denied', (await web.patch('/mcp-management/policy', headers=bearer(users['a-member']),json=denied_policy)).status_code == 403)
        check('ordinary user emergency write denied', (await web.post('/mcp-management/emergency-disable', headers=bearer(users['a-member']),json={'reason':'Isolated denial'})).status_code == 403)
        bad = await web.patch('/mcp-management/policy', headers=bearer(owner), json={
            'enabled': True, 'read_only': True, 'allowed_tool_ids': list(NAMES), 'allowed_roles': ['user'],
            'reason': 'isolated', 'tenant_id': 'untrusted'})
        check('client tenant selector rejected', bad.status_code == 422)
        metadata = (await web.get('/.well-known/oauth-authorization-server/mcp-oauth')).json()
        check('AS metadata issuer and S256 only', metadata['issuer'] == issuer and metadata['code_challenge_methods_supported'] == ['S256'])
        async with httpx.AsyncClient(trust_env=False, timeout=20) as raw:
            pr = (await raw.get(origin+'/.well-known/oauth-protected-resource/mcp')).json()
            check('protected resource metadata', pr['resource'] == resource and pr['authorization_servers'] == [issuer])
            response = await raw.post(resource, json={})
            check('missing bearer challenge advertises metadata', response.status_code == 401 and 'resource_metadata=' in response.headers['www-authenticate'])

        def authorization_fields(scope='tasks:read workload:read'):
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            return verifier, dict(client_id=client_id, response_type='code', redirect_uri=redirect, resource=resource,
                scope=scope, state=secrets.token_urlsafe(32), code_challenge=challenge, code_challenge_method='S256')

        async def begin(alias='a-member', scope='tasks:read workload:read'):
            verifier, fields = authorization_fields(scope)
            response = await web.get('/mcp-oauth/authorize', params=fields)
            check('authorization creates browser-bound consent transaction', response.status_code == 302 and '/#/mcp/consent?' in response.headers['location'])
            request_id = parse_qs(urlsplit(response.headers['location']).fragment.split('?', 1)[1])['request'][0]
            preview = await web.post('/mcp-oauth/requests/'+request_id+'/preview', headers=bearer(users[alias]), json={})
            check('consent bound to actual session', preview.status_code == 200 and set(preview.json()['tools']) <= set(NAMES))
            sensitive.add(preview.json()['csrf'])
            sensitive.update(cookie.value for cookie in web.cookies.jar)
            return verifier, fields, request_id, preview.json()

        async def approve(alias='a-member', scope='tasks:read workload:read', accept=True):
            verifier, fields, request_id, preview = await begin(alias, scope)
            response = await web.post('/mcp-oauth/requests/'+request_id+'/decision', headers=bearer(users[alias]), json={'approve': accept, 'csrf': preview['csrf']})
            check('explicit consent decision', response.status_code == 200)
            uri = response.json()['redirect_uri']
            query = callback_query(uri, fields['state'], issuer)
            check('client validates state and authorization response issuer', query.get('state') == [fields['state']] and query.get('iss') == [issuer])
            for state, iss, name in ((secrets.token_urlsafe(32), issuer, 'state'), (fields['state'], 'https://wrong.invalid', 'issuer')):
                try:
                    callback_query(uri, state, iss)
                except ValueError:
                    check('client rejects '+name+' mismatch before token exchange', True)
                else:
                    check('client rejects '+name+' mismatch before token exchange', False)
            if not accept:
                check('denied consent returns no code', query.get('error') == ['access_denied'] and 'code' not in query)
                return None
            sensitive.add(query['code'][0])
            return dict(grant_type='authorization_code', client_id=client_id, code=query['code'][0],
                        redirect_uri=redirect, resource=resource, code_verifier=verifier)

        async def exchange(form):
            response = await web.post('/mcp-oauth/token', data=form)
            check('actual authorization-code exchange', response.status_code == 200)
            value = response.json()
            sensitive.update(value[key] for key in ('access_token', 'refresh_token'))
            check('bounded opaque access and rotating refresh issued', value['access_token'].startswith('mcp_at.') and value['refresh_token'].startswith('mcp_rt.') and 0 < value['expires_in'] <= 300)
            return value

        async def grant(alias='a-member', scope='tasks:read workload:read'):
            return await exchange(await approve(alias, scope))

        @asynccontextmanager
        async def mcp(token):
            async with httpx.AsyncClient(headers=bearer(token), trust_env=False, timeout=25) as transport:
                async with Client(streamable_http_client(resource, http_client=transport), read_timeout_seconds=30) as client:
                    yield client, transport

        async def valid(token):
            response = await web.post('/mcp-oauth/validate', headers={'X-MCP-Service': cfg['oauth_service_secret']}, json={'token': token, 'tool_id': None})
            return response

        async def denied(token, name):
            check(name, (await valid(token)).status_code in (401, 403))
            async with httpx.AsyncClient(trust_env=False, timeout=20) as raw:
                check(name+' at MCP resource', (await raw.post(resource, headers=bearer(token), json={})).status_code in (401,403))

        for changed in ({'redirect_uri': 'https://evil.invalid/cb'}, {'code_challenge_method': 'plain'},
                        {'code_challenge': ''}, {'resource': backend+'/tasks'}, {'scope': 'tasks:write'}, {'state': 'short'}):
            _, fields = authorization_fields(); fields.update(changed)
            response = await web.get('/mcp-oauth/authorize', params=fields)
            check('invalid authorization '+next(iter(changed)), response.status_code == 400 and 'location' not in response.headers and response.json()['error'])
        await approve(accept=False)
        _, _, expired_request, _ = await begin()
        await mutate('authorization_expired', request_id=expired_request)
        check('expired consent transaction denied', (await web.post('/mcp-oauth/requests/'+expired_request+'/preview', headers=bearer(users['a-member']), json={})).status_code == 403)
        expired_code = await approve()
        await mutate('code_expired', code=expired_code['code'])
        check('expired code denied before token issuance', (await web.post('/mcp-oauth/token',data=expired_code)).status_code == 400)
        verifier, fields, rid, preview = await begin()
        response = await web.post('/mcp-oauth/requests/'+rid+'/decision', headers=bearer(users['a-member']), json={'approve':True, 'csrf':secrets.token_urlsafe(32)})
        check('consent CSRF rejection', response.status_code == 403)
        response = await web.post('/mcp-oauth/requests/'+rid+'/preview', headers=bearer(users['b-member']), json={})
        check('consent cannot change authenticated user or tenant', response.status_code == 403)
        async with httpx.AsyncClient(base_url=backend, trust_env=False) as cookieless:
            response = await cookieless.post('/mcp-oauth/requests/'+rid+'/preview', headers=bearer(users['a-member']), json={})
            check('consent requires original browser cookie', response.status_code == 403)
        form = await approve()
        check('code requires original exact redirect', (await web.post('/mcp-oauth/token',data={**form,'redirect_uri':redirect+'/other'})).status_code == 400)
        check('code requires explicit resource', (await web.post('/mcp-oauth/token',data={k:v for k,v in form.items() if k!='resource'})).status_code == 400)
        check('code requires PKCE verifier', (await web.post('/mcp-oauth/token',data={k:v for k,v in form.items() if k!='code_verifier'})).status_code == 400)
        wrong = {**form, 'code_verifier':secrets.token_urlsafe(48)}
        response = await web.post('/mcp-oauth/token', data=wrong)
        check('incorrect PKCE rejected as OAuth error', response.status_code == 400 and response.json()['error'] == 'invalid_grant')
        pair = await exchange(form)
        check('code cannot be replayed', (await web.post('/mcp-oauth/token', data=form)).status_code == 400)
        await denied(pair['access_token'], 'code replay revokes issued credential family')
        pair = await grant()
        pair_b = await grant('b-member')
        check('MCP access token rejected by business REST', (await web.get('/tasks/page', headers=bearer(pair['access_token']))).status_code == 401)
        check('delegation control needs service authentication', (await web.post('/mcp-oauth/delegate', json={'token':pair['access_token'], 'tool_id':NAMES[0]})).status_code == 401)
        delegated = await web.post('/mcp-oauth/delegate', headers={'X-MCP-Service':cfg['oauth_service_secret']}, json={'token':pair['access_token'], 'tool_id':NAMES[0]})
        check('separate tool-bound REST credential issued', delegated.status_code == 200 and delegated.json()['credential'].startswith('mcp_dt.') and delegated.json()['credential'] != pair['access_token'])
        dt = delegated.json()['credential']
        sensitive.add(dt)
        grant_id = delegated.json()['grant_id']
        check('delegated REST executes as exact user', (await web.get('/auth/me', headers=bearer(dt))).json()['id'] == fixture['users']['a-member'])
        check('downstream credential cannot write', (await web.post('/tasks', headers=bearer(dt), json={})).status_code in (401,403))
        check('downstream credential cannot read other endpoint', (await web.get('/users', headers=bearer(dt))).status_code in (401,403))
        check('downstream credential bound to tool REST path', (await web.get('/tasks/activity', headers=bearer(dt))).status_code in (401,403))
        await denied(dt, 'downstream credential rejected at MCP audience')
        async with mcp(pair['access_token']) as (client, transport):
            tools = (await client.list_tools()).tools
            check('OAuth MCP discovery exactly five read-only tools', tuple(t.name for t in tools) == NAMES and all(t.annotations.read_only_hint for t in tools))
            for name, args in ((NAMES[0], {}), (NAMES[1], {'task_id':fixture['tasks']['a-main']}),
                               (NAMES[2], {}), (NAMES[3], {'task_id':fixture['tasks']['a-main']}), (NAMES[4], {})):
                result = await client.call_tool(name, args)
                check('real delegated tool '+name, not result.is_error and result.structured_content['source'] == 'rest')
                check('tool results exclude credentials/private fixture data', all(x not in result.model_dump_json() for x in ('mcp_at.', 'mcp_rt.', 'mcp_dt.', 'PRIVATE_MEDIA_SENTINEL', 'PRIVATE_KEY_SENTINEL', 'access_token', 'hashed_password')))
            try:
                await mutate('disclosure_title', value='prefix'+pair['access_token']+'suffix')
                result = await client.call_tool(NAMES[1], {'task_id':fixture['tasks']['a-main']})
                check('opaque credential redacted next to ordinary text', not result.is_error and pair['access_token'] not in result.model_dump_json())
            finally:
                await mutate('disclosure_title', value='Synthetic a-main')
            for hidden in ('a-peer-task', 'b-main'):
                result = await client.call_tool(NAMES[1], {'task_id':fixture['tasks'][hidden]})
                check('object/group/tenant denial '+hidden, result.is_error)
            for token, alias in ((pair_b['access_token'],'b-member'), (pair['access_token'],'a-member')):
                transport.headers.update(bearer(token))
                result = await client.call_tool(NAMES[4], {}, meta={'user_id': fixture['users']['a-owner']})
                check('same MCP client resolves identity per request', not result.is_error and result.structured_content['data']['user_id'] == fixture['users'][alias])
            async def concurrent(index):
                # Independent HTTP pools share the resource, never authorization state.
                alias, token = ('b-member',pair_b['access_token']) if index%2 else ('a-member',pair['access_token'])
                async with mcp(token) as (other, _):
                    result = await other.call_tool(NAMES[4], {})
                    check('concurrent user credential isolation', not result.is_error and result.structured_content['data']['user_id'] == fixture['users'][alias])
            # Bounded batches exercise concurrent identities without exceeding the advertised ceiling.
            for start in (0, 8, 16):
                await asyncio.gather(*(concurrent(i) for i in range(start, min(start+8,20))))
        async with httpx.AsyncClient(trust_env=False, timeout=20) as raw:
            for headers, body, status, name in (
                ({**bearer(pair['access_token']), 'Origin':'https://evil.invalid'}, {}, 403, 'hostile Origin'),
                ({**bearer(pair['access_token']), 'Host':'evil.invalid'}, {}, 403, 'hostile Host'),
                (bearer(pair['access_token']), {'method':'tools/call', 'params':[]}, 400, 'malformed protocol params'),
                (bearer(pair['access_token']), {'method':'tools/call','params':{'name':'zeaplay_delete_task'}}, 403, 'unapproved write tool')):
                check(name, (await raw.post(resource, headers=headers, json=body)).status_code == status)
            check('resource request size bounded', (await raw.post(resource, headers=bearer(pair['access_token']), content=b'x'*32769)).status_code == 413)
            check('duplicate authorization rejected', (await raw.post(resource, headers=[('Authorization','Bearer '+pair['access_token'])]*2, json={})).status_code == 401)
            check('duplicate Origin rejected', (await raw.post(resource,headers=[*bearer(pair['access_token']).items(),('Origin','https://evil.invalid'),('Origin',origin)],json={})).status_code == 403)
            check('query token shortcut rejected', (await raw.post(resource+'?access_token=synthetic', headers=bearer(pair['access_token']),json={})).status_code == 400)
            # Fill the bounded body readers, then disconnect every owned socket.
            host = urlsplit(origin)
            writers=[]
            try:
                for _ in range(16):
                    _, writer = await asyncio.open_connection(host.hostname, host.port)
                    writer.write(('POST /mcp HTTP/1.1\r\nHost: '+host.netloc+'\r\nAuthorization: Bearer '+pair['access_token']+'\r\nContent-Length: 10000\r\n\r\n{').encode())
                    await writer.drain(); writers.append(writer)
                limited = False
                for _ in range(20):
                    response=await raw.post(resource,headers=bearer(pair['access_token']),json={})
                    if response.status_code==429: limited=True; break
                    await asyncio.sleep(.02)
                check('transport concurrency bounded to sixteen', limited)
            finally:
                for writer in writers: writer.close()
                for writer in writers: await writer.wait_closed()
            recovered = False
            for _ in range(20):
                response=await raw.post(resource,headers=bearer(pair['access_token']),json={})
                if response.status_code!=429: recovered=True; break
                await asyncio.sleep(.02)
            check('disconnect releases all transport capacity', recovered)
        narrow = await grant(scope='workload:read')
        response = await web.post('/mcp-oauth/token',data=dict(grant_type='refresh_token',client_id=client_id,
            resource=resource,refresh_token=narrow['refresh_token'],scope='tasks:read workload:read'))
        check('refresh cannot enlarge approved scopes', response.status_code == 400 and response.json()['error'] == 'invalid_scope')
        async with mcp(narrow['access_token']) as (client,_):
            check('scope narrows discovery', [t.name for t in (await client.list_tools()).tools] == [NAMES[4]])
        response = await web.post('/mcp-oauth/delegate', headers={'X-MCP-Service':cfg['oauth_service_secret']}, json={'token':narrow['access_token'], 'tool_id':NAMES[0]})
        check('scope independently enforced at delegation', response.status_code == 403)
        await policy(allowed_tool_ids=[NAMES[4]])
        response = await web.post('/mcp-oauth/delegate', headers={'X-MCP-Service':cfg['oauth_service_secret']}, json={'token':pair['access_token'], 'tool_id':NAMES[0]})
        check('tenant tool disable enforced on existing access token', response.status_code == 403)
        check('existing downstream credential invalidated by tool disable', (await web.get('/tasks/page', headers=bearer(dt))).status_code in (401,403))
        check('tenant B independent of tenant A policy', (await valid(pair_b['access_token'])).status_code == 200)
        await policy(allowed_roles=['owner'])
        await denied(pair['access_token'], 'role allowlist enforced')
        await policy(enabled=False)
        await denied(pair['access_token'], 'tenant disable enforced')
        check('revocation accepted while policy disabled', (await web.post('/mcp-oauth/revoke',
            data={'client_id':client_id,'token':pair['access_token']})).status_code == 200)
        await policy()
        await denied(pair['access_token'], 'policy restore cannot resurrect disconnected grant')
        # Rotation and replay revoke the whole credential family.
        rotating = await grant()
        refresh_form = dict(grant_type='refresh_token', client_id=client_id, resource=resource, refresh_token=rotating['refresh_token'])
        response = await web.post('/mcp-oauth/token', data=refresh_form)
        check('refresh rotates credential', response.status_code == 200 and response.json()['refresh_token'] != rotating['refresh_token'])
        rotated = response.json()
        sensitive.update(rotated[key] for key in ('access_token','refresh_token'))
        check('refresh replay rejected', (await web.post('/mcp-oauth/token', data=refresh_form)).status_code == 400)
        await denied(rotated['access_token'], 'refresh replay revokes family')
        for action in ('wrong_issuer', 'wrong_audience', 'credential_expired'):
            token = (await grant())['access_token']
            await mutate(action, credential=token)
            await denied(token, action+' rejected')
        expiring = await grant()
        authority = (await valid(expiring['access_token'])).json()
        await mutate('grant_expired', grant_id=authority['grant_id'])
        await denied(expiring['access_token'], 'expired grant rejected')
        revoked = await grant()
        await web.post('/mcp-oauth/revoke', data={'client_id':client_id, 'token':revoked['access_token']})
        await denied(revoked['access_token'], 'explicit token revocation')
        for action, changed, restored in (('role','manager','user'), ('tenant','b','a'), ('status','DEACTIVATED','ACTIVE')):
            current = await grant()
            await mutate(action, alias='a-member', value=changed)
            await denied(current['access_token'], 'current account '+action+' change invalidates grant')
            await mutate(action, alias='a-member', value=restored)
            users['a-member'] = await login('a-member')
            await denied(current['access_token'], 'restored account cannot resurrect old grant '+action)
        linked = await grant()
        check('parent session logout succeeds', (await web.post('/auth/logout',headers=bearer(users['a-member']))).status_code in (200,204))
        await denied(linked['access_token'], 'parent session logout invalidates OAuth grant')
        users['a-member'] = await login('a-member')
        peer = await grant('a-peer')
        peer_id = (await valid(peer['access_token'])).json()['grant_id']
        check('ordinary user cannot revoke another user grant', (await web.post('/mcp-oauth/grants/'+peer_id+'/revoke',headers=bearer(users['a-member']))).status_code == 404)
        check('tenant owner can revoke current tenant grant', (await web.post('/mcp-oauth/grants/'+peer_id+'/revoke',headers=bearer(owner))).status_code == 200)
        await denied(peer['access_token'], 'management revocation invalidates access')
        last = await grant()
        state = await snapshot()
        (root/'oauth-management-snapshot.json').write_text(json.dumps(state, indent=2))
        check('genuine durable connection status', state['connections']['available'] and any(x['id']==grant_id for x in state['connections']['items']) and state['overview']['active_connections'] > 0)
        check('management aggregate matches enforceable grant statuses', state['connections']['total'] <= 50 and
              state['overview']['active_connections'] == sum(item['status'] == 'active' for item in state['connections']['items']))
        check('management grant inventory excludes foreign tenant user', all(item['user_id'] != fixture['users']['b-member'] for item in state['connections']['items']))
        check('genuine audit events available', state['activity']['available'] and any(x['event']=='consent_approved' for x in state['activity']['items']))
        check('management exposes no credentials', all(secret not in json.dumps(state) for secret in (pair['access_token'], pair['refresh_token'], dt, cfg['oauth_service_secret'], 'mcp_at.', 'mcp_dt.', 'mcp_rt.')))
        check('external production clients remain disabled', state['overview']['remote_access_enabled'] is False)
        foreign_revoke = await web.post('/mcp-oauth/grants/'+(await valid(pair_b['access_token'])).json()['grant_id']+'/revoke', headers=bearer(owner))
        check('tenant A owner cannot revoke tenant B grant', foreign_revoke.status_code == 404)
        response = await web.post('/mcp-management/emergency-disable', headers=bearer(owner), json={'reason':'Isolated emergency verification'})
        check('durable emergency disable accepted', response.status_code == 200)
        await denied(last['access_token'], 'emergency disables existing grants')
        current = (await snapshot())['configuration']
        response = await web.patch('/mcp-management/policy', headers=bearer(owner), json={
            'enabled':True,'read_only':True,'allowed_tool_ids':list(NAMES),'allowed_roles':['user'], 'reason':'Cannot clear lock','expected_revision':current['revision']})
        check('ordinary policy update cannot clear emergency lock', response.status_code == 409)
        check('emergency leaves other tenant active', (await valid(pair_b['access_token'])).status_code == 200)
        storage = await web.post('/__phase4a__/mutate',headers={'X-Fixture-Control':cfg['attestation_secret']},
            json={'action':'storage_check','secrets':sorted(sensitive)})
        check('six MCP tables contain no raw credentials codes or CSRF', storage.status_code == 200 and storage.json() == {'raw_secrets_found':False})
        logs = '\n'.join(path.read_text(errors='replace') for path in root.iterdir() if path.is_file() and path.suffix in ('.log','.jsonl'))
        check('running service logs contain no known secrets before cleanup redaction', all(secret not in logs for secret in sensitive))


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    try:
        asyncio.run(exercise(root, sys.argv[2]))
        outcome = 'PASS'
    except BaseException as exc:
        outcome = 'FAIL'
        checks.append({'failure_type': type(exc).__name__})
        # No exception text: libraries can embed credentials and protocol URLs.
    report = {'result':outcome, 'checks':checks}
    (root/'oauth-results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'result':outcome,'checks':len(checks),'failed':[x for x in checks if x.get('result')=='FAIL'], 'evidence':str(root/'oauth-results.json')}))
    raise SystemExit(0 if outcome == 'PASS' else 1)
