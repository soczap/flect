"""Bounded, read-only application scanning. Never imports or runs target code."""
import ast
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import subprocess
import tempfile
import time
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote
from urllib.request import Request, build_opener, ProxyHandler
from .compat import NoRedirect
from .compat import canonical, digest

MAX_FILES = 2000
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 32 * 1024 * 1024
SKIP = {'.git', '.svn', '.hg', 'node_modules', '.venv', 'venv', '.scanner-venv', '__pycache__', 'dist', 'build', '.ssh', '.aws', '.codex', '.config', '.agents', 'data', 'models', 'logs', 'captures', 'uploads', 'media', 'test-results', 'graphify-out', '.pytest_cache', '.ruff_cache', 'vendor', 'trinetra.egg-info'}
TEXT_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json', '.yml', '.yaml', '.toml', '.tf', '.txt', '.ini', '.cfg', '.conf', '.env', '.xml', '.lock', '.pem', '.key'}
SEVERITY = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}


def now():
    return datetime.now(timezone.utc).isoformat()


def redact(text):
    text = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', '[REDACTED PRIVATE KEY]', text)
    text = re.sub(r'(?i)((?:password|passwd|secret(?:[_-]?key)?|api[_-]?key|access[_-]?token|authorization)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b', '[REDACTED CREDENTIAL]', text)
    text = re.sub(r'(?i)(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', text)
    return text[:1500]


def read_sources(source):
    """Return bounded snapshots, explicit exclusions. ZIPs are never extracted."""
    root = Path(source)
    files, gaps, total = {}, [], 0
    def accept(name, raw):
        nonlocal total
        if len(files) >= MAX_FILES or total + len(raw) > MAX_TOTAL_BYTES:
            raise OverflowError('project scan budget reached')
        if len(raw) > MAX_FILE_BYTES:
            gaps.append({'code': 'oversize_file', 'detail': name}); return
        if b'\x00' in raw[:4096]:
            return
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            gaps.append({'code': 'non_utf8_file', 'detail': name}); return
        total += len(raw)
        files[name] = {'text': text, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    def eligible(name):
        p = PurePosixPath(name)
        if p.name == '.env' or (p.name.startswith('.env.') and p.name not in {'.env.example','.env.sample','.env.template'}):
            gaps.append({'code':'sensitive_config_excluded','detail':name + ': live environment values were not read.'}); return False
        return not (set(p.parts) & SKIP) and (p.suffix.lower() in TEXT_SUFFIXES or p.name.startswith(('Dockerfile','Containerfile')) or p.name in {'requirements.txt', 'Pipfile', 'Gemfile'} or p.name.startswith('.env'))
    try:
        if root.is_file() and root.suffix.lower() == '.zip':
            with zipfile.ZipFile(root) as archive:
                members = archive.infolist()
                if len(members) > 10000:
                    raise ValueError('archive has too many entries')
                expanded = 0
                for member in members:
                    p = PurePosixPath(member.filename)
                    mode = member.external_attr >> 16
                    if p.is_absolute() or '..' in p.parts or '\\' in member.filename or stat.S_ISLNK(mode) or member.flag_bits & 1:
                        raise ValueError('unsafe archive member, symlink or encrypted archive')
                    expanded += member.file_size
                    if expanded > MAX_TOTAL_BYTES or member.file_size > MAX_FILE_BYTES or (member.compress_size and member.file_size / member.compress_size > 200):
                        raise ValueError('archive exceeds decompression safety limits')
                    if member.is_dir() or not eligible(member.filename):
                        continue
                    if member.filename in files:
                        raise ValueError('duplicate archive path')
                    accept(member.filename, archive.read(member))
        elif root.is_dir():
            root = root.resolve()
            entries_seen = 0
            for directory, dirs, names in os.walk(root, followlinks=False):
                entries_seen += len(dirs) + len(names)
                if entries_seen > 15000: raise OverflowError('directory-entry budget reached')
                dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(directory) / d).is_symlink())
                for name in sorted(names):
                    path = Path(directory) / name
                    relative = path.relative_to(root).as_posix()
                    if not eligible(relative):
                        continue
                    try:
                        # No symlink traversal and no devices/FIFOs. The root itself was registered separately.
                        if path.is_symlink() or not path.resolve().is_relative_to(root):
                            gaps.append({'code': 'symlink_excluded', 'detail': relative}); continue
                        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                        with os.fdopen(fd, 'rb') as stream:
                            info = os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode):
                                gaps.append({'code': 'non_regular_file', 'detail': relative}); continue
                            accept(relative, stream.read(MAX_FILE_BYTES + 1))
                    except OSError:
                        gaps.append({'code': 'unreadable_file', 'detail': relative})
        else:
            raise ValueError('project source must be an existing directory or ZIP archive')
    except OverflowError as exc:
        gaps.append({'code': 'scan_truncated', 'detail': str(exc)})
    return files, gaps


class ScanContext:
    def __init__(self, app_id, scan_id, files, source=None):
        self.app_id, self.scan_id, self.files = app_id, scan_id, files
        self.events, self.findings, self.gaps, self.dependencies = [], [], [], []
        self.timestamp = now()
        self.repository = 'repository:' + app_id
        self.source = Path(source) if source else None

    def event(self, domain, kind, attrs, entities=None):
        value = {'id': self.scan_id + '-' + str(len(self.events) + 1), 'source': 'soc-scanner-v1',
                 'domain': domain, 'timestamp': self.timestamp, 'event_type': kind,
                 'entities': entities or [self.repository], 'attributes': attrs}
        self.events.append(value)
        return value['id']

    def finding(self, rule, title, severity, description, remediation, path=None, line=None, confidence='medium', extra=None):
        def family(rule_id):
            if rule_id.startswith('AUTH-'): return 'authenticated'
            if rule_id.startswith('DEP-'): return 'dependencies'
            if rule_id.startswith('HTTP-'): return 'http'
            if 'BANDIT-' in rule_id: return 'bandit'
            return 'native'
        group = family(rule)
        limit = {'dependencies':150,'http':20,'bandit':300,'native':200,'authenticated':40}[group]
        if sum(family(f['rule_id'])==group for f in self.findings) >= limit:
            code = 'finding_limit_' + group
            if not any(g['code'] == code for g in self.gaps):
                self.gaps.append({'code':code,'detail':f'{group} finding budget ({limit}) reached; that check is incomplete.'})
            return
        location = {'path': path, 'line': line}
        source_scope = 'test' if path and ('tests' in PurePosixPath(path).parts or PurePosixPath(path).name.startswith('test_')) else 'application'
        attrs = {'rule_id': rule, 'title': title, 'severity': severity, 'confidence': confidence,'source_scope':source_scope,
                 'description': description, 'remediation': remediation, 'location': location, **(extra or {})}
        if path in self.files:
            file = self.files[path]
            attrs['file_sha256'] = file['sha256']
            lines = file['text'].splitlines()
            if line and line <= len(lines):
                attrs['snippet'] = redact(lines[line - 1]) if not rule.startswith('SECRET-') else '[Secret content withheld; inspect the cited local file and line.]'
        eid = self.event('dependency' if rule.startswith('DEP-') else 'repository', 'security_finding', attrs)
        self.findings.append({'id': 'finding-' + digest([self.scan_id, rule, location, extra])[:16],
                              **attrs, 'evidence_ids': [eid], 'status': 'needs_review'})


def static_checks(ctx):
    calls = {
        'eval': ('PY-EVAL', 'Dynamic evaluation of code', 'high', 'Replace dynamic evaluation with explicit parsing or dispatch.'),
        'exec': ('PY-EXEC', 'Dynamic execution of code', 'high', 'Avoid executing constructed code; use explicit functions.'),
        'os.system': ('PY-SHELL', 'Shell command execution', 'high', 'Use argument arrays without a shell and validate untrusted values.'),
        'pickle.loads': ('PY-PICKLE', 'Potentially unsafe deserialization', 'high', 'Avoid pickle for data that could be attacker-controlled.'),
        'pickle.load': ('PY-PICKLE', 'Potentially unsafe deserialization', 'high', 'Avoid pickle for data that could be attacker-controlled.'),
        'yaml.unsafe_load': ('PY-YAML', 'Unsafe YAML loader', 'high', 'Use yaml.safe_load for untrusted input.'),
    }
    for path, file in ctx.files.items():
        text = file['text']
        if path.endswith('.py'):
            try:
                tree = ast.parse(text)
            except (SyntaxError, RecursionError):
                ctx.gaps.append({'code': 'python_parse_failed', 'detail': path}); continue
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    aliases.update({a.asname or a.name: a.name for a in node.names})
                elif isinstance(node, ast.ImportFrom) and node.module:
                    aliases.update({a.asname or a.name: node.module + '.' + a.name for a in node.names})
            def qualified(node):
                if isinstance(node, ast.Name): return aliases.get(node.id, node.id)
                if isinstance(node, ast.Attribute): return qualified(node.value) + '.' + node.attr
                return ''
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call): continue
                name = qualified(node.func)
                match = calls.get(name)
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                if name.startswith('subprocess.') and isinstance(kwargs.get('shell'), ast.Constant) and kwargs['shell'].value is True:
                    match = ('PY-SHELL', 'Subprocess shell execution enabled', 'high', 'Use shell=False with an argument array and validate inputs.')
                if name == 'yaml.load':
                    loader = kwargs.get('Loader') or (node.args[1] if len(node.args) > 1 else None)
                    if qualified(loader) not in {'yaml.SafeLoader', 'yaml.CSafeLoader'}:
                        match = ('PY-YAML', 'YAML loader safety not established', 'medium', 'Use yaml.safe_load or explicitly select SafeLoader.')
                if name.endswith('.execute') and node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                    match = ('PY-SQL', 'SQL statement constructed dynamically', 'high', 'Use parameterized database queries; review input provenance.')
                if name.endswith('.run') and isinstance(kwargs.get('debug'), ast.Constant) and kwargs['debug'].value is True:
                    match = ('PY-DEBUG', 'Debug server enabled in source', 'medium', 'Disable debug mode in deployed environments.')
                if match:
                    rule, title, severity, fix = match
                    ctx.finding(rule, title, severity, f'AST matched {name} at this location. Input reachability and exploitability require review.', fix, path, node.lineno)
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', line) or re.search(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b', line):
                ctx.finding('SECRET-MATERIAL', 'Potential credential material in project', 'high', 'A private-key marker or credential-format pattern was found. Credential validity was not tested.', 'Remove the material from source; review history and rotate it if it is a real active credential.', path, line_no, 'high')
            elif re.search(r'''(?i)\b(?:password|api_key|secret_key|access_token)\s*[=:]\s*["'][^"'\s]{8,}["']''', line) and not re.search(r'(?i)example|placeholder|changeme|test.only|os\.environ|process\.env|\$\{', line):
                ctx.finding('SECRET-LITERAL', 'Potential hardcoded secret', 'medium', 'A secret-like assignment has a literal value. It may be test data and needs review.', 'Use a secret manager or runtime configuration; rotate real exposed credentials.', path, line_no)
            if path.endswith(('.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs')):
                patterns = [(r'\beval\s*\(', 'JS-EVAL', 'Dynamic JavaScript evaluation', 'Avoid eval on values influenced by users.'),
                            (r'\.innerHTML\s*=', 'JS-HTML', 'HTML assignment requires input review', 'Use textContent for plain text or a vetted HTML sanitizer.'),
                            (r'(?:child_process\s*\.\s*exec|execSync)\s*\(', 'JS-SHELL', 'Shell execution pattern', 'Prefer an argument-array process API and validate inputs.')]
                for pattern, rule, title, fix in patterns:
                    if re.search(pattern, line):
                        ctx.finding(rule, title, 'medium', 'A source pattern matched; this check does not establish attacker-controlled data flow.', fix, path, line_no)
            if path.endswith(('.yml', '.yaml', '.json', '.tf')):
                if re.search(r'(?i)privileged\s*:\s*true|hostNetwork\s*:\s*true', line):
                    ctx.finding('CONFIG-PRIVILEGED', 'Privileged container or host networking setting', 'high', 'A privileged deployment setting appears in configuration; deployment state is unknown.', 'Remove unneeded privileges and apply least-privilege container settings.', path, line_no)
                if re.search(r'permissions\s*:\s*write-all', line):
                    ctx.finding('CI-WRITE-ALL', 'Broad CI workflow permissions', 'high', 'The workflow text grants write-all permissions; effective organization policy is not evaluated.', 'Declare the minimum permissions per job and protect untrusted pull-request workflows.', path, line_no)
                if re.search(r'''["']?Action["']?\s*:\s*["']\*["']''', line):
                    ctx.finding('IAM-WILDCARD', 'Wildcard IAM action in policy', 'medium', 'A wildcard action appears in a policy. Effect, conditions and explicit denies require policy evaluation.', 'Scope actions/resources and validate the effective policy.', path, line_no)
        if PurePosixPath(path).name.startswith(('Dockerfile', 'Containerfile')):
            users = re.findall(r'(?im)^\s*USER\s+(\S+)', text)
            if users and users[-1].split(':')[0] in {'0', 'root'}:
                ctx.finding('CONTAINER-ROOT', 'Container selects root user', 'medium', 'The final explicit USER instruction selects root. Runtime overrides are unknown.', 'Use a non-root runtime user with narrowly scoped filesystem permissions.', path, next(i for i,l in enumerate(text.splitlines(),1) if re.match(r'\s*USER\s+(root|0)\b',l,re.I)))
            elif not users:
                ctx.gaps.append({'code': 'container_user_unknown', 'detail': path + ': final base-image user must be inspected.'})


def bandit_checks(ctx):
    executable = Path(os.environ.get('SOC_BANDIT',str(Path(__file__).resolve().parent.parent / '.scanner-venv/bin/bandit')))
    python_files = [(p,f) for p,f in ctx.files.items() if p.endswith('.py')]
    if not python_files:
        return {'name':'bandit_python','status':'not_run','detail':'No Python source files in the selected snapshot.'}
    if not executable.is_file():
        return {'name':'bandit_python','status':'not_run','detail':'Install the pinned scanner-requirements.txt into .scanner-venv to enable Bandit.'}
    # Copy only bounded Python snapshots to a fresh directory. No project config, hooks,
    # .pth files or scripts are executed; Bandit uses its own isolated environment.
    with tempfile.TemporaryDirectory(prefix='soc-bandit-') as temp:
        folder = Path(temp)
        for path,file in python_files:
            destination = folder / path
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(file['text'])
        output = folder / 'scanner-output.json'
        config = folder / 'scanner-config.yaml'; config.write_text('{}\n')
        try:
            run = subprocess.run([str(executable),'-r',str(folder),'-c',str(config),'--ignore-nosec','-f','json','-o',str(output),'-q'],
                                 cwd=temp,env={'PATH':'/usr/bin:/bin','HOME':temp,'PYTHONNOUSERSITE':'1'},
                                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60,check=False)
            if run.returncode not in {0,1} or not output.is_file() or output.stat().st_size > 8_000_000:
                raise ValueError('Bandit did not produce bounded JSON output')
            report = json.loads(output.read_text())
            suppressed_assertions = 0
            for match in report.get('results',[]):
                path = Path(match['filename']).relative_to(folder).as_posix()
                if path not in ctx.files: continue
                rule = str(match.get('test_id','unknown'))
                if rule == 'B101' and ('tests' in PurePosixPath(path).parts or PurePosixPath(path).name.startswith('test_')):
                    suppressed_assertions += 1; continue
                secret = rule in {'B105','B106','B107'}
                ctx.finding(('SECRET-' if secret else '')+'BANDIT-'+rule, 'Bandit: '+str(match.get('test_name',rule)).replace('_',' '),
                            str(match.get('issue_severity','medium')).lower(),
                            ('Potential hardcoded credential; value withheld.' if secret else redact(str(match.get('issue_text',''))[:1000]))+' Static analysis finding; reachability and exploitability require review.',
                            'Review the cited code and Bandit rule guidance; use safer APIs or justify and document the usage.',path,match.get('line_number'),
                            str(match.get('issue_confidence','medium')).lower(),extra={'scanner':'Bandit','rule_reference':match.get('more_info'),'cwe':match.get('issue_cwe')})
            errors = report.get('errors',[])
            if errors: ctx.gaps.append({'code':'bandit_parse_errors','detail':f'{len(errors)} Python files could not be fully analyzed.'})
            return {'name':'bandit_python','status':'partial' if errors else 'completed','files':len(python_files),'reported_findings':len(report.get('results',[])),
                    'test_assertions_excluded':suppressed_assertions,'detail':'Bandit AST checks; project suppression comments are ignored. B101 assertions in test files are excluded; other test findings are labeled.'}
        except Exception as exc:
            ctx.gaps.append({'code':'bandit_failed','detail':type(exc).__name__})
            return {'name':'bandit_python','status':'failed','detail':type(exc).__name__}


def dependency_inventory(ctx):
    seen = set()
    def add(name, version, ecosystem, path, direct=None, ref=None):
        if not isinstance(name, str) or not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_.@/+:-]{1,200}', name) or not re.fullmatch(r'[A-Za-z0-9_.+!-]{1,100}', version):
            ctx.gaps.append({'code': 'dependency_version_unresolved', 'detail': path + ': dependency version is not pinned or supported.'}); return
        key = (name, version, ecosystem, path)
        if key in seen: return
        seen.add(key)
        ctx.dependencies.append({'name': name, 'version': version, 'ecosystem': ecosystem, 'path': path, 'direct': direct, 'ref': ref})
    for path, file in list(ctx.files.items()):
        name, text = PurePosixPath(path).name, file['text']
        try:
            if name.startswith('requirements') and name.endswith('.txt'):
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'): continue
                    match = re.match(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([A-Za-z0-9_.+!-]+)(?:\s|;|$)', line)
                    if match: add(match[1], match[2], 'PyPI', path, True)
                    else: ctx.gaps.append({'code': 'dependency_version_unresolved', 'detail': path + ': an unpinned/include/unsupported requirement was not queried.'})
            elif name == 'pyproject.toml':
                data = tomllib.loads(text)
                declared = list(data.get('project',{}).get('dependencies',[]))
                for group in data.get('project',{}).get('optional-dependencies',{}).values(): declared.extend(group)
                unresolved = 0
                for line in declared:
                    match = re.match(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([A-Za-z0-9_.+!-]+)(?:\s|;|$)',line)
                    if match: add(match[1],match[2],'PyPI',path,True)
                    else: unresolved += 1
                if unresolved: ctx.gaps.append({'code':'dependency_ranges','detail':f'{path}: {unresolved} declared dependency ranges are not exact installed versions.'})
            elif name == 'package-lock.json':
                data = json.loads(text)
                if isinstance(data.get('packages'), dict):
                    for package_path, package in data['packages'].items():
                        if not package_path or not isinstance(package, dict): continue
                        package_name = package.get('name') or package_path.rsplit('node_modules/',1)[-1]
                        add(package_name, package.get('version'), 'npm', path, None, package_path)
                else:
                    def visit(packages, depth=0):
                        if depth > 50: raise ValueError('dependency tree too deep')
                        for package_name, package in packages.items():
                            add(package_name, package.get('version'), 'npm', path, depth == 0)
                            visit(package.get('dependencies', {}), depth+1)
                    visit(data.get('dependencies', {}))
            elif name == 'package.json' and not any(PurePosixPath(p).parent == PurePosixPath(path).parent and PurePosixPath(p).name == 'package-lock.json' for p in ctx.files):
                data = json.loads(text)
                for section in ('dependencies','devDependencies'):
                    for dependency, version in data.get(section, {}).items(): add(dependency, version, 'npm', path, True)
                ctx.gaps.append({'code': 'transitive_dependencies_unknown', 'detail': path + ': package-lock.json is absent.'})
            elif path.endswith('.json'):
                data = json.loads(text)
                if isinstance(data, dict) and data.get('bomFormat') == 'CycloneDX':
                    for component in data.get('components', []):
                        purl = component.get('purl', '')
                        if purl.startswith(('pkg:pypi/', 'pkg:npm/')):
                            ecosystem = 'PyPI' if purl.startswith('pkg:pypi/') else 'npm'
                            body = unquote(purl.split('/',1)[1].split('?',1)[0])
                            package_name = body.rsplit('@',1)[0] if '@' in body[1:] else body
                            add(package_name, component.get('version'), ecosystem, path, None, component.get('bom-ref'))
                    if 'dependencies' not in data:
                        ctx.gaps.append({'code': 'sbom_graph_unknown', 'detail': path + ': dependency relationships are absent.'})
        except (ValueError, TypeError, AttributeError, RecursionError):
            ctx.gaps.append({'code': 'manifest_parse_failed', 'detail': path})
    if ctx.source and ctx.source.is_dir():
        environment = ctx.source / '.venv'
        if environment.is_dir() and not environment.is_symlink():
            count = 0
            for metadata in sorted(environment.glob('lib/python*/site-packages/*.dist-info/METADATA'))[:500]:
                if metadata.is_symlink() or not metadata.resolve().is_relative_to(environment.resolve()): continue
                try:
                    raw = metadata.read_bytes() if metadata.stat().st_size <= MAX_FILE_BYTES else b''
                    text = raw.decode('utf-8')
                    name = re.search(r'(?m)^Name:\s*(\S+)',text); version = re.search(r'(?m)^Version:\s*(\S+)',text)
                    if name and version:
                        relative = metadata.relative_to(ctx.source).as_posix()
                        # Keep only package headers in memory; hash refers to original metadata bytes.
                        ctx.files[relative] = {'text':f'Name: {name[1]}\nVersion: {version[1]}\n','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
                        add(name[1],version[1],'PyPI',relative,None); count += 1
                except (OSError,UnicodeDecodeError): continue
            if count:
                ctx.gaps.append({'code':'environment_scope','detail':f'{count} package versions came from local .venv metadata. These are not verified as the deployed container versions; target Python was not executed.'})
    if len(ctx.dependencies) > 500:
        ctx.dependencies = ctx.dependencies[:500]
        ctx.gaps.append({'code': 'dependency_limit', 'detail': 'Only the first 500 pinned package records were analyzed.'})
    for dependency in ctx.dependencies:
        dependency['evidence_id'] = ctx.event('dependency', 'dependency_inventory', dependency.copy())
    return ctx.dependencies


def osv_lookup(ctx, enabled=False, opener=None):
    if not enabled:
        return {'name': 'dependency_advisories', 'status': 'not_run', 'detail': 'Enable OSV lookup to send package names and versions to api.osv.dev.'}
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())
    queried, errors, started = 0, [], time.monotonic()
    for offset in range(0, len(ctx.dependencies), 50):
        batch = ctx.dependencies[offset:offset+50]
        if time.monotonic() - started > 60:
            errors.append('OSV time budget reached'); break
        payload = {'queries': [{'package': {'name': d['name'], 'ecosystem': d['ecosystem']}, 'version': d['version']} for d in batch]}
        try:
            request = Request('https://api.osv.dev/v1/querybatch', data=canonical(payload).encode(), headers={'Content-Type':'application/json', 'User-Agent':'SOC/0.2'})
            with opener.open(request, timeout=15) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000: raise ValueError('advisory response too large')
            results = json.loads(raw)['results']
            if len(results) != len(batch): raise ValueError('advisory response count mismatch')
            for dependency, result in zip(batch, results):
                queried += 1
                if result.get('next_page_token'):
                    errors.append('OSV pagination truncated for ' + dependency['name'])
                ids = sorted({v['id'] for v in result.get('vulns', []) if isinstance(v.get('id'),str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',v['id'])})
                if ids:
                    ctx.finding('DEP-OSV', 'Known vulnerability advisories for pinned dependency', 'high',
                                f"OSV returned {len(ids)} advisory IDs for {dependency['ecosystem']} {dependency['name']} {dependency['version']}. Runtime reachability and exploitability are not established.",
                                'Review the cited advisories, select a fixed supported version, update the lockfile and retest. Severity is a review priority, not a CVSS score.', dependency['path'], confidence='high',
                                extra={'package': dependency['name'], 'version': dependency['version'], 'ecosystem': dependency['ecosystem'], 'advisory_ids': ids[:100], 'advisory_source': 'https://api.osv.dev/v1/querybatch', 'queried_at': now()})
            ctx.event('dependency','advisory_query_result', {'queried_packages':len(batch),'response_sha256':hashlib.sha256(raw).hexdigest(),'matched_packages':sum(bool(r.get('vulns')) for r in results), 'source':'https://api.osv.dev/v1/querybatch'})
        except Exception as exc:
            errors.append(type(exc).__name__ + ': advisory lookup failed')
    ctx.gaps.extend({'code':'advisory_lookup_incomplete','detail':e} for e in errors)
    return {'name':'dependency_advisories','status':'partial' if errors else 'completed','queried':queried,'total':len(ctx.dependencies),'errors':errors}


def validate_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('target must be an HTTP(S) URL without credentials, query or fragment')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port in {1111, 1112}:
        raise ValueError('SOC and model control endpoints cannot be scan targets')
    hostname = parsed.hostname.lower()
    if hostname in {'metadata.google.internal','instance-data'}:
        raise ValueError('cloud metadata endpoints are forbidden')
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)})
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
            raise ValueError('target resolves to a forbidden address')
    if not addresses:
        raise ValueError('target did not resolve')
    return parsed, port, addresses[0]


def http_checks(ctx, url):
    if not url:
        return {'name':'http_posture','status':'not_run','detail':'No application URL supplied.'}
    try:
        parsed, port, address = validate_target(url)
        # Pin the validated IP for the entire request. Do not follow redirects or use proxies.
        sock = socket.create_connection((address, port), timeout=8)
        conn = http.client.HTTPConnection(address, port, timeout=8)
        try:
            if parsed.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            conn.sock = sock
            conn.request('GET', parsed.path or '/', headers={'Host':parsed.netloc,'User-Agent':'SOC-read-only-check/0.2','Accept':'text/html,application/json'})
            response = conn.getresponse()
            headers = {k.lower():v for k,v in response.getheaders()}
            # Drain only a bounded prefix; no crawling, authentication or exploit payloads.
            body = response.read(65536)
            evidence = {'url':url,'resolved_address':address,'status':response.status,
                        'headers':{k:redact(v) for k,v in headers.items() if k in {'content-type','content-security-policy','x-content-type-options','x-frame-options','strict-transport-security','referrer-policy'}},
                        'body_prefix_sha256':hashlib.sha256(body).hexdigest(), 'redirect_followed':False}
            eid = ctx.event('network','http_observation',evidence)
            missing = []
            if 'text/html' in headers.get('content-type',''):
                for key in ('content-security-policy','x-content-type-options','referrer-policy'):
                    if key not in headers: missing.append(key)
                if 'x-frame-options' not in headers and 'frame-ancestors' not in headers.get('content-security-policy',''):
                    missing.append('frame embedding protection')
            if parsed.scheme == 'https' and 'strict-transport-security' not in headers:
                missing.append('strict-transport-security')
            if missing:
                ctx.finding('HTTP-HEADERS','Missing browser security headers','low', 'The sampled response is missing: ' + ', '.join(missing) + '. This is a hardening observation, not proof of exploitability.', 'Apply appropriate response headers for this application and verify on representative routes.', confidence='high', extra={'url':url,'observation_evidence_id':eid})
            cookies = response.headers.get_all('Set-Cookie') or []
            weak = sum('httponly' not in c.lower() or (parsed.scheme == 'https' and 'secure' not in c.lower()) for c in cookies)
            if weak:
                ctx.finding('HTTP-COOKIE','Cookie attributes need review','medium',f'{weak} sampled cookies lack HttpOnly or HTTPS Secure attributes. Cookie contents were not retained.', 'Review each cookie purpose and apply Secure, HttpOnly and SameSite where appropriate.', confidence='high',extra={'url':url})
            return {'name':'http_posture','status':'completed','http_status':response.status,'evidence_id':eid,'requests':1}
        finally:
            conn.close(); sock.close()
    except Exception as exc:
        ctx.gaps.append({'code':'http_check_failed','detail':type(exc).__name__ + ': the supplied URL could not be checked.'})
        return {'name':'http_posture','status':'failed','detail':type(exc).__name__}


def scan_project(source, app_id, scan_id, target_url=None, osv=False, progress=None, auth=None):
    progress = progress or (lambda stage: None)
    started = time.monotonic()
    progress('Reading bounded project snapshot')
    files, gaps = read_sources(source)
    ctx = ScanContext(app_id, scan_id, files, source)
    ctx.gaps.extend(gaps)
    progress('Checking source, secrets and deployment configuration')
    static_checks(ctx)
    coverage = [{'name':'source_and_configuration','status':'completed' if files else 'not_run','files':len(files),
                 'detail':'Python AST rules, JS/TS source patterns, secret patterns, Docker/CI/IAM configuration patterns. No target code is executed.'}]
    progress('Running isolated Bandit Python analysis')
    coverage.append(bandit_checks(ctx))
    progress('Reading lockfiles and software bills of materials')
    dependency_inventory(ctx)
    manifest = [{'path':p,'sha256':f['sha256'],'bytes':f['bytes']} for p,f in sorted(files.items())]
    manifest_hash = digest(manifest)
    ctx.event('repository','project_snapshot',{'manifest_sha256':manifest_hash,'file_count':len(files),'scan_id':scan_id,'ruleset':'soc-native-0.2'})
    coverage.append({'name':'dependency_inventory','status':'completed' if ctx.dependencies else 'not_run','packages':len(ctx.dependencies),'detail':'Exact requirements/pyproject pins, npm package-lock, exact package.json versions, CycloneDX PyPI/npm components, and local .venv metadata where present.'})
    progress('Checking known dependency advisories' if osv else 'Advisory lookup not enabled')
    coverage.append(osv_lookup(ctx, osv))
    progress('Checking the supplied application URL' if target_url else 'No application URL supplied')
    coverage.append(http_checks(ctx, target_url))
    from .auth_testing import authenticated_checks
    progress('Checking authenticated sessions and declared access policies' if auth else 'Authenticated testing not enabled')
    coverage.append(authenticated_checks(ctx, target_url, auth))
    ctx.gaps.extend([
        {'code':'runtime_reachability_unknown','detail':'Static patterns and advisory matches do not establish attacker-controlled reachability or exploitation.'},
        {'code':'cloud_permissions_unknown','detail':'Effective cloud permissions, credential activity and actual deployment state require independent telemetry; no compromise path is invented.'},
        {'code':'scope_limited','detail':'HTTP posture samples one URL. Authenticated checks, when enabled, compare only declared GET routes and content markers. No automatic crawling, state-changing requests, injection testing, or complete business-logic/language coverage.'}])
    for check in coverage:
        if check['status'] in {'not_run','failed','partial'}:
            ctx.gaps.append({'code':'check_' + check['status'],'detail':check['name'] + ': ' + check.get('detail','incomplete coverage')})
    ctx.findings.sort(key=lambda f:(SEVERITY[f['severity']],f['rule_id'],f['location']['path'] or ''))
    return {'scan_id':scan_id,'app_id':app_id,'created_at':ctx.timestamp,'status':'completed_with_gaps' if ctx.gaps else 'completed',
            'verdict':'review_required' if ctx.findings else 'no_findings_in_checked_scope',
            'findings':ctx.findings,'dependencies':ctx.dependencies,'coverage':coverage,'gaps':ctx.gaps,
            'manifest':manifest,'manifest_sha256':manifest_hash,'events':ctx.events,
            'latency_ms':round((time.monotonic()-started)*1000,2),'ruleset':'soc-native-0.2',
            'limits':['No finding is a certification of exploitability. No findings does not establish that the application is secure.', 'Secret values are withheld; files are read without executing target code.']}
