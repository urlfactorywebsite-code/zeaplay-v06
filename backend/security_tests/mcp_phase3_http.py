"""Real management HTTP/session checks; only the run-owned attested fixture.

Invoked by run_rest_integration.py --management-check. No dependency overrides,
shared database, production credentials, OAuth or external network are used.
"""
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
import uuid


def main(root):
    root = root.resolve()
    config = json.loads((root / 'broker.json').read_text())
    run = config['run_id']
    assert (root / 'owned.json').is_file()
    assert json.loads((root / 'owned.json').read_text())['run_id'] == run
    assert config['mode'] == 'isolated-test' and len(run) == 32
    origin = urlsplit(config['backend_origin'])
    assert origin.scheme == 'http' and origin.hostname == '127.0.0.1'
    assert origin.port and origin.path == '' and not origin.username and not origin.query and not origin.fragment
    results = []
    credentials = [config['attestation_secret'], *(a['password'] for a in config['accounts'].values())]

    def guard(event, args):
        if event == 'socket.connect' and isinstance(args[1], tuple) and args[1][:2] != ('127.0.0.1', origin.port):
            raise RuntimeError('Management audit outbound connection denied')
        if event == 'socket.getaddrinfo' and args[0] != '127.0.0.1':
            raise RuntimeError('Management audit DNS denied')
    sys.addaudithook(guard)

    def request(method, path, token=None, body=None, headers=None):
        assert path.startswith('/') and not path.startswith('//')
        connection = http.client.HTTPConnection('127.0.0.1', origin.port, timeout=10)
        fields = {'Content-Type': 'application/json', **(headers or {})}
        if token:
            fields['Authorization'] = 'Bearer ' + token
        try:
            connection.request(method, path, body=None if body is None else json.dumps(body), headers=fields)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            assert len(raw) <= 1024 * 1024
            return response.status, json.loads(raw) if raw else None, dict(response.getheaders())
        finally:
            connection.close()

    def check(name, passed):
        results.append({'case': name, 'result': 'PASS' if passed else 'FAIL'})
        if not passed:
            raise RuntimeError(name)

    try:
        # Attest before sending even synthetic passwords to the fixture.
        nonce = secrets.token_hex(32)
        status, attestation, _ = request('GET', '/__phase2b__/attest?nonce=' + nonce)
        expected = hmac.new(config['attestation_secret'].encode(), (run + ':' + nonce).encode(), hashlib.sha256).hexdigest()
        check('Owned backend attestation before authentication', status == 200 and attestation['run_id'] == run
              and hmac.compare_digest(attestation['proof'], expected))
        tokens = {}
        for alias in ('a-owner', 'a-member', 'a-manager', 'b-member'):
            account = config['accounts'][alias]
            status, response, _ = request('POST', '/auth/login', body={'email': account['email'], 'password': account['password']})
            check('Real login ' + alias, status == 200)
            tokens[alias] = response['token']['access_token']
            credentials.extend(response['token'][key] for key in ('access_token', 'refresh_token'))
        owner = tokens['a-owner']
        tenant_a, tenant_b = (str(uuid.uuid5(uuid.UUID(run), 'tenant-' + name)) for name in ('a', 'b'))
        policy_body = {'enabled': True, 'read_only': True, 'allowed_tool_ids': ['zeaplay_list_tasks'],
                       'allowed_roles': ['user'], 'reason': 'Owned fixture review'}
        expected_tools = {'zeaplay_list_tasks', 'zeaplay_get_task', 'zeaplay_list_overdue_tasks',
                          'zeaplay_list_subtasks', 'zeaplay_get_workload_summary'}
        for base in ('/mcp-management', '/api/mcp-management'):
            check(base + ' signed-out denial', request('GET', base)[0] == 401)
            status, snapshot, headers = request('GET', base, owner, headers={'X-Tenant-ID': tenant_b})
            check(base + ' authenticated tenant ignores spoofed header', status == 200 and snapshot['tenant_context'] == tenant_a)
            check(base + ' snapshot is uncached', headers.get('cache-control') == 'no-store')
            check(base + ' exact read-only catalog', {t['id'] for t in snapshot['tools']} == expected_tools
                  and len(snapshot['tools']) == 5 and all(t['read_only'] and not t['enabled'] for t in snapshot['tools']))
            check(base + ' genuine unavailable readiness', snapshot['overview']['active_connections'] is None
                  and snapshot['overview']['health_status'] == 'not_monitored' and snapshot['overview']['endpoint'] is None
                  and not snapshot['overview']['remote_access_enabled'] and not snapshot['connections']['available']
                  and not snapshot['activity']['available'] and not snapshot['configuration']['persisted'])
            encoded = json.dumps(snapshot)
            check(base + ' no issued credentials exposed', all(secret not in encoded for secret in credentials))
            for alias in ('a-member', 'a-manager', 'b-member'):
                check(base + ' current role denies ' + alias, request('GET', base, tokens[alias],
                    headers={'X-Role': 'owner', 'X-Tenant-ID': tenant_a})[0] == 403)
                check(base + ' mutation denies ' + alias, request('PATCH', base + '/policy', tokens[alias], policy_body)[0] == 403)
            check(base + ' query tenant denied', request('GET', base + '?tenant_id=' + tenant_b, owner)[0] == 422)
            check(base + ' body tenant denied', request('PATCH', base + '/policy', owner, {**policy_body, 'tenant_id': tenant_b})[0] == 422)
            check(base + ' valid policy cannot activate service', request('PATCH', base + '/policy', owner, policy_body)[0] == 503)
            check(base + ' emergency stop never claims success', request('POST', base + '/emergency-disable', owner, {'reason': 'Stop'})[0] == 503)
            status, error, _ = request('PATCH', base + '/policy', owner, {'REVIEW_SECRET_FIELD': 'REVIEW_SECRET_VALUE'})
            check(base + ' validation does not reflect names or values', status == 422 and 'REVIEW_SECRET' not in json.dumps(error))
            check(base + ' rejected writes leave snapshot unchanged', request('GET', base, owner)[1] == snapshot)
        status, policy, _ = request('GET', '/navigation', owner)
        check('Real navigation includes MCP Settings', status == 200 and any(p['id'] == 'settings.mcp-management' and p['visible'] for p in policy['pages']))
        rules = {p['id']: {key: p[key] for key in ('enabled', 'hidden', 'allowedRoles')} for p in policy['pages']}
        rules['settings.mcp-management']['enabled'] = False
        status, updated, _ = request('PUT', '/navigation', owner, {'version': policy['version'], 'pages': rules})
        check('Owner can disable module in owned tenant', status == 200)
        for base in ('/mcp-management', '/api/mcp-management'):
            check(base + ' real navigation denies direct read', request('GET', base, owner)[0] == 403)
            check(base + ' real navigation denies mutation', request('PATCH', base + '/policy', owner, policy_body)[0] == 403)
        status, other, _ = request('GET', '/navigation', tokens['b-member'])
        check('Other tenant navigation unchanged', status == 200 and other['tenantId'] == tenant_b
              and next(p for p in other['pages'] if p['id'] == 'settings.mcp-management')['enabled'])
        status, audit, _ = request('GET', '/logs/audit?entity_type=navigation_policy', owner)
        check('Navigation save has genuine tenant-attributed audit row', status == 200 and len(audit['items']) == 1
              and audit['items'][0]['entity_id'] == tenant_a)
        rules['settings.mcp-management']['enabled'] = True
        status, _, _ = request('PUT', '/navigation', owner, {'version': updated['version'], 'pages': rules})
        check('Restore owned fixture navigation', status == 200)
        check('Logout real management session', request('POST', '/auth/logout', owner)[0] == 204)
        check('Revoked management session rejected', request('GET', '/mcp-management', owner)[0] == 401)
    except Exception as exc:
        # Never include requests, response bodies, passwords or bearer strings.
        if not results or results[-1]['result'] != 'FAIL':
            results.append({'case': 'Management audit execution', 'result': 'FAIL', 'type': type(exc).__name__})
    success = all(item['result'] == 'PASS' for item in results)
    evidence = {'result': 'PASS' if success else 'FAIL', 'checks': len(results), 'results': results}
    (root / 'management-results.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps({'management': evidence['result'], 'checks': len(results),
                      'failed': [item['case'] for item in results if item['result'] != 'PASS']}))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main(Path(sys.argv[1])))
