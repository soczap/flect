"""Explicitly scoped GET authorization tests. Credentials live only in scan memory."""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import uuid
from http.cookies import SimpleCookie
from .scanner import validate_target, now

MAX_ROUTES = 10
MAX_BODY = 65536
MAX_SECONDS = 90


def validate_auth_config(value, target_url):
    if value is None:
        return None
    if not target_url:
        raise ValueError('Authenticated tests require an application target URL.')
    if not isinstance(value, dict) or set(value) - {'primary', 'secondary', 'routes'}:
        raise ValueError('Authenticated tests accept primary, optional secondary, and routes.')

    def route(raw):
        if not isinstance(raw, dict) or set(raw) - {'path', 'marker', 'deny_secondary'}:
            raise ValueError('Each route needs a path, response marker, and optional deny_secondary boolean.')
        path, marker = raw.get('path'), raw.get('marker')
        # Deliberately literal origin-relative paths, without query strings or encoded separators.
        if not isinstance(path, str) or not re.fullmatch(r'/[A-Za-z0-9_./~:@+-]{0,500}', path) or '//' in path or any(p in {'.', '..'} for p in path.split('/')):
            raise ValueError('Use a literal /path on the target origin; queries, fragments and encoded paths are unsupported.')
        if not isinstance(marker, str) or not 3 <= len(marker) <= 200 or any(ord(c) < 32 for c in marker):
            raise ValueError('Each route needs a non-sensitive response marker of 3–200 characters.')
        if type(raw.get('deny_secondary', False)) is not bool:
            raise ValueError('deny_secondary must be a boolean.')
        return {'path': path, 'marker': marker, 'deny_secondary': raw.get('deny_secondary', False)}

    def session(raw):
        if not isinstance(raw, dict) or set(raw) != {'kind', 'credential', 'verification'}:
            raise ValueError('A session needs kind, credential, and verification route.')
        kind, secret = raw['kind'], raw['credential']
        if kind not in {'bearer', 'cookie'} or not isinstance(secret, str) or not 1 <= len(secret) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in secret.replace(' ', '')) or '\r' in secret or '\n' in secret:
            raise ValueError('Supply a bearer token or Cookie header value without control characters.')
        if kind == 'bearer' and not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', secret):
            raise ValueError('Enter only the bearer token, without the Bearer prefix.')
        if kind == 'cookie':
            parts = secret.split(';')
            if any(not re.fullmatch(r'\s*[A-Za-z0-9_.~-]+=[^;\s,]*\s*', part) for part in parts):
                raise ValueError('Cookie value must contain name=value pairs separated by semicolons.')
            cookie = SimpleCookie()
            try:
                cookie.load(secret)
            except Exception:
                raise ValueError('Invalid Cookie header value.') from None
            if not cookie or len(cookie) != len(parts) or any(name.lower() in {'path', 'domain', 'expires', 'max-age', 'secure', 'httponly', 'samesite'} for name in cookie):
                raise ValueError('Supply a request Cookie header, without Set-Cookie attributes.')
        return {'kind': kind, 'credential': secret, 'verification': route(raw['verification'])}

    primary = session(value.get('primary'))
    secondary = session(value['secondary']) if value.get('secondary') else None
    routes = value.get('routes')
    if not isinstance(routes, list) or not 1 <= len(routes) <= MAX_ROUTES:
        raise ValueError(f'Specify 1–{MAX_ROUTES} protected GET routes.')
    routes = [route(r) for r in routes]
    if len({r['path'] for r in routes}) != len(routes):
        raise ValueError('Protected route paths must be unique.')
    if any(r['deny_secondary'] for r in routes) and not secondary:
        raise ValueError('A secondary session is required for role or object-access comparisons.')
    if secondary and secondary['credential'] == primary['credential']:
        raise ValueError('Primary and secondary credentials must be different.')
    persisted_paths = [target_url, primary['verification']['path']] + [r['path'] for r in routes]
    if secondary: persisted_paths.append(secondary['verification']['path'])
    for session_value in (primary, secondary):
        if not session_value: continue
        secrets = [session_value['credential']]
        if session_value['kind'] == 'cookie':
            cookie = SimpleCookie(); cookie.load(session_value['credential'])
            secrets.extend(m.value for m in cookie.values() if m.value)
        if any(secret in path for secret in secrets for path in persisted_paths):
            raise ValueError('Session secrets must not appear in target URLs or paths.')
    return {'primary': primary, 'secondary': secondary, 'routes': routes}


def public_auth_config(config):
    """Persist scope only: no credentials, markers, or credential fingerprints."""
    if not config:
        return None
    return {'primary_kind': config['primary']['kind'],
            'primary_verification_path': config['primary']['verification']['path'],
            'secondary_kind': config['secondary']['kind'] if config['secondary'] else None,
            'secondary_verification_path': config['secondary']['verification']['path'] if config['secondary'] else None,
            'routes': [{'path': r['path'], 'deny_secondary': r['deny_secondary']} for r in config['routes']],
            'method': 'GET', 'max_seconds': MAX_SECONDS, 'credentials_persisted': False}


def auth_headers(session, invalid=False):
    if not session:
        return {}
    credential = session['credential']
    if invalid:
        nonce = 'soc-invalid-' + uuid.uuid4().hex
        if session['kind'] == 'cookie':
            cookie = SimpleCookie(); cookie.load(credential)
            credential = '; '.join(name + '=' + nonce for name in cookie)
        else:
            credential = nonce
    return {'Authorization': 'Bearer ' + credential} if session['kind'] == 'bearer' else {'Cookie': credential}


def request_sample(target, path, headers, timeout):
    """No redirect, proxy, cookie jar, decompression, or raw response persistence."""
    parsed, port, address = target
    started = time.monotonic()
    sock = socket.create_connection((address, port), timeout=timeout)
    remaining = timeout - (time.monotonic() - started)
    if remaining <= 0:
        sock.close(); raise TimeoutError('Connection exceeded request deadline')
    sock.settimeout(remaining)
    conn = http.client.HTTPConnection(address, port, timeout=remaining)
    def expire():
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(remaining, expire); timer.daemon = True; timer.start()
    try:
        if parsed.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        conn.sock = sock
        conn.request('GET', path, headers={'Host': parsed.netloc, 'User-Agent': 'SOC-auth-check/0.3',
                     'Accept': 'application/json,text/html', 'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache', **headers})
        response = conn.getresponse()
        body = response.read(MAX_BODY + 1)
        mime = response.getheader('Content-Type', '').split(';')[0].lower()
        return {'status': response.status, 'body': body[:MAX_BODY], 'truncated': len(body) > MAX_BODY,
                'content_type': mime if mime in {'application/json','text/html','text/plain'} else 'other'}
    finally:
        timer.cancel(); conn.close(); sock.close()


def authenticated_checks(ctx, target_url, config):
    if not config:
        return {'name': 'authenticated_testing', 'status': 'not_run', 'detail': 'No authenticated test scope or session supplied.'}
    start = time.monotonic()
    coverage = {'name': 'authenticated_testing', 'status': 'completed', 'requests': 0, 'cases': [],
                'primary_verified': False, 'secondary_verified': False,
                'detail': 'GET-only session and authorization comparisons on explicitly supplied routes. Response bodies and credentials are not retained.'}
    try:
        target = validate_target(target_url)
        if target[0].scheme != 'https' and not ipaddress.ip_address(target[2]).is_loopback:
            raise ValueError('Authenticated testing requires HTTPS except on loopback.')
        coverage['origin'] = target[0].scheme + '://' + target[0].netloc

        def sample(route, context, session=None, invalid=False):
            remaining = MAX_SECONDS - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutError('Authenticated scan budget exhausted')
            coverage['requests'] += 1
            response = request_sample(target, route['path'], auth_headers(session, invalid), min(8, remaining))
            attrs = {'path': route['path'], 'method': 'GET', 'session_context': context, 'status': response['status'],
                     'marker_matched': route['marker'].encode() in response['body'],
                     'body_prefix_sha256': hashlib.sha256(response['body']).hexdigest(),
                     'body_truncated': response['truncated'], 'content_type': response['content_type'],
                     'captured_at': now(), 'redirect_followed': False, 'resolved_address': target[2]}
            eid = ctx.event('network', 'authorization_http_observation', attrs)
            return {**attrs, 'evidence_id': eid}

        def success(response):
            return 200 <= response['status'] < 300 and response['marker_matched']

        def denied(response):
            return response['status'] in {401, 403} or 300 <= response['status'] < 400

        def verify(session, label):
            route = session['verification']
            baseline = sample(route, label, session)
            anonymous = sample(route, label + '_anonymous')
            invalid = sample(route, label + '_invalid', session, True)
            verified = success(baseline) and denied(anonymous) and denied(invalid)
            coverage['cases'].append({'path': route['path'], 'check': label + '_session_verification',
                                      'outcome': 'verified' if verified else 'inconclusive',
                                      'responses': [baseline, anonymous, invalid]})
            if not verified:
                ctx.gaps.append({'code': label + '_session_unverified', 'detail': 'The ' + label + ' session could not be distinguished from anonymous/invalid access on its verification route. Protected checks for this identity are inconclusive.'})
            return verified

        coverage['primary_verified'] = verify(config['primary'], 'primary')
        if not coverage['primary_verified']:
            coverage['status'] = 'partial'
            return coverage
        if config['secondary']:
            coverage['secondary_verified'] = verify(config['secondary'], 'secondary')
            if not coverage['secondary_verified']:
                coverage['status'] = 'partial'

        for route in config['routes']:
            baseline = sample(route, 'primary', config['primary'])
            if not success(baseline):
                coverage['cases'].append({'path': route['path'], 'check': 'protected_access', 'outcome': 'inconclusive', 'responses': [baseline]})
                coverage['status'] = 'partial'
                ctx.gaps.append({'code': 'protected_baseline_missing', 'detail': route['path'] + ': primary response did not match the expected successful content; comparisons skipped.'})
                continue
            comparisons = [('anonymous', None, False), ('invalid', config['primary'], True)]
            if route['deny_secondary'] and coverage['secondary_verified']:
                comparisons.append(('secondary', config['secondary'], False))
            elif route['deny_secondary']:
                coverage['cases'].append({'path': route['path'], 'check': 'secondary_access', 'outcome': 'inconclusive', 'responses': []})
            for label, session, invalid in comparisons:
                response = sample(route, label, session, invalid)
                matched = success(response)
                outcome = 'unexpected_access' if matched else 'denied' if denied(response) else 'inconclusive'
                responses = [baseline, response]
                if label == 'secondary':
                    recheck = sample(config['secondary']['verification'], 'secondary_recheck', config['secondary'])
                    responses.append(recheck)
                    if not success(recheck):
                        outcome = 'inconclusive'; matched = False
                        ctx.gaps.append({'code': 'secondary_session_expired', 'detail': 'Second session could not be revalidated after the access comparison; no denial or policy mismatch is concluded for this case.'})
                coverage['cases'].append({'path': route['path'], 'check': label + '_access', 'outcome': outcome, 'responses': responses})
                if outcome == 'inconclusive':
                    coverage['status'] = 'partial'
                    ctx.gaps.append({'code': 'access_result_ambiguous', 'detail': route['path'] + ': ' + label + ' response did not conclusively grant or deny the expected content.'})
                if matched:
                    ctx.finding('AUTH-' + label.upper(), 'Protected content returned to ' + label + ' session', 'high',
                        'The primary session was verified separately. This route returned HTTP ' + str(response['status']) + ' and the operator-specified content marker to the ' + label + ' context, contrary to the declared access policy. This reproduces a policy mismatch; marker specificity and intended authorization still require analyst review.',
                        'Enforce authentication and resource-level authorization on the server; verify the declared access policy and repeat the test after remediation.',
                        confidence='high', extra={'url_path': route['path'], 'category': 'authorization', 'validation': 'observed_policy_mismatch',
                        'observation_evidence_ids': [baseline['evidence_id'], response['evidence_id']], 'test_case': label + '_access',
                        'cwe': {'id': 862}, 'rule_reference': 'https://owasp.org/www-project-web-security-testing-guide/stable/4-Web_Application_Security_Testing/05-Authorization_Testing/02-Testing_for_Bypassing_Authorization_Schema'})
    except Exception as exc:
        coverage['status'] = 'partial' if coverage['requests'] else 'failed'
        # Exception messages may contain target-controlled strings; never persist them.
        ctx.gaps.append({'code': 'authenticated_test_incomplete', 'detail': type(exc).__name__ + ': authenticated checks stopped. Inspect the recorded cases; untested routes remain unknown.'})
    finally:
        coverage['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
    return coverage
