"""Aliyun-only disposable Harness feasibility probe; never use production home.

Runs pinned, already-installed artifacts with network=none and no published ports.
Only generated temporary directories and labelled probe containers are mutated.
No LLM/provider credentials, production config, database or user data are mounted.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import uuid
from urllib.parse import quote

HARNESS = Path('/root/liao/DepartmentKnowledgeBase/deepseek-harness')
NODE = Path('/usr/local/lib/nodejs/node-v22.22.3-linux-x64/bin/node')
HERE = Path(__file__).resolve().parent
IMAGE = 'pgvector/pgvector:0.8.6-pg17-bookworm'
LABEL = 'department.identity-probe'
if os.uname().sysname != 'Linux' or not HARNESS.is_dir():
    raise SystemExit('Run this probe on Aliyun via SSH; local execution is unsupported.')
ROOT = Path(tempfile.mkdtemp(prefix='department-identity-probe-'))
CONTAINERS = []
RESULTS = []
baseline = {}


def command(args, *, data=None, timeout=30):
    r = subprocess.run(args, input=data, text=True, capture_output=True, timeout=timeout)
    if r.returncode:
        # Do not log startup URLs or credentials, including in failures.
        error = re.sub(r'([?]token=)[^\s]+', r'\1[REDACTED]', r.stderr + r.stdout)
        raise RuntimeError(f'{args[0:2]} exited {r.returncode}: {error[-2500:]}')
    return (r.stdout + (r.stderr if args[:2] == ['docker', 'logs'] else '')).strip()


def record(name, ok, detail=None):
    result = dict(test=name, ok=bool(ok), detail=detail)
    RESULTS.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def health():
    result = {}
    for port, path in [(3081, '/health'), (3080, '/')]:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as r:
                result[str(port)] = r.status
        except urllib.error.HTTPError as e:
            result[str(port)] = e.code
        except OSError as e:
            result[str(port)] = type(e).__name__
    return result


def launch(identity):
    available = int(re.search(r'MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text())[1])
    if available < 900 * 1024:
        raise RuntimeError('Insufficient available memory to safely launch another probe')
    home = ROOT / identity
    home.mkdir(mode=0o700)
    os.chown(home, 10001, 10001)
    workspace = home / 'workspace'
    workspace.mkdir(mode=0o700)
    os.chown(workspace, 10001, 10001)
    marker = workspace / 'identity.txt'
    marker.write_text(identity)
    os.chown(marker, 10001, 10001)
    name = f'department-identity-probe-{ROOT.name.rsplit("-", 1)[-1]}-{identity}'
    args = ['docker', 'create', '--pull=never', '--name', name,
            '--label', f'{LABEL}=true', '--network', 'none',
            '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--memory', '640m',
            '--memory-swap', '640m', '--cpus', '0.5', '--pids-limit', '128',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
            '--env', 'HOME=/home/probe', '--env', 'DSH_HOME=/home/probe/dsh',
            '--env', 'NODE_OPTIONS=--max-old-space-size=256',
            '--env', 'TSX_TSCONFIG_PATH=/opt/harness/tsconfig.json',
            '--workdir', '/home/probe/workspace',
            '--mount', f'type=bind,src={home},dst=/home/probe',
            '--mount', f'type=bind,src={NODE},dst=/usr/local/bin/node,readonly',
            '--mount', f'type=bind,src={HERE},dst=/probe,readonly']
    for part in ['apps', 'packages', 'vendor', 'native', 'node_modules',
                 'package.json', 'pnpm-workspace.yaml', 'tsconfig.json', 'tsconfig.base.json']:
        args += ['--mount', f'type=bind,src={HARNESS / part},dst=/opt/harness/{part},readonly']
    args += ['--entrypoint', '/usr/local/bin/node', IMAGE,
             '--expose-internals',
             '--import', '/opt/harness/node_modules/tsx/dist/esm/index.mjs',
             '/opt/harness/apps/cli/src/bin.ts', '--profile', 'web',
             '--no-open', '--port', '39080']
    command(args)
    CONTAINERS.append(name)
    started = time.monotonic()
    command(['docker', 'start', name])
    token = wait_ready(name)
    record(f'{identity}: started', True, {'seconds': round(time.monotonic()-started, 2)})
    return name, token, home


def wait_ready(name, previous_token=None):
    for _ in range(150):
        logs = command(['docker', 'logs', name])
        matches = re.findall(r'dsh web: http://127\.0\.0\.1:39080/\?token=([^\s]+)', logs)
        if matches and matches[-1] != previous_token:
            return matches[-1]
        status = json.loads(command(['docker', 'inspect', '--format', '{{json .State}}', name]))
        if not status['Running']:
            raise RuntimeError(f'{name} failed: {status}; ' + re.sub(r'token=\S+', 'token=[REDACTED]', logs[-2500:]))
        time.sleep(1)
    raise RuntimeError(f'{name} startup timed out')


def client(name, data):
    return json.loads(command(['docker', 'exec', '-i', name, 'node', '/probe/client.mjs'],
                              data=json.dumps(data), timeout=25))


def http(name, path, cookie=None, body=None):
    headers = {}
    if cookie:
        headers['Cookie'] = cookie
    if body is not None:
        headers['Content-Type'] = 'application/json'
    return client(name, {'op':'http', 'path':path, 'headers':headers,
                         'method':'GET' if body is None else 'POST', **({} if body is None else {'body':body})})


def authenticate(name, token):
    r = http(name, f'/?token={token}')
    assert r['status'] == 303 and r['cookie'], 'token exchange failed'
    return r['cookie'].split(';', 1)[0]


def rpc(name, cookie, method, args):
    r = http(name, '/api/' + method, cookie, {
        'type':'client-request', 'rpcId':str(uuid.uuid4()), 'method':method, 'payload':{'args':args}})
    assert r['status'] == 200, f'{method}: HTTP {r["status"]}'
    result = json.loads(r['body'])['result']
    assert result['ok'], f'{method}: {result.get("error")}'
    return result.get('value')


class Broker:
    """Feasibility adapter, NOT a production login/gateway implementation.

    Trusted fixture principal selects its runtime. Browser never receives upstream
    cookie/token. A read-only preflight refreshes expired auth before each mutation;
    mutations are dispatched once, never automatically replayed after a failure.
    """
    def __init__(self):
        self.runtimes = {}
        self.dispatches = 0

    def register(self, principal, space, name, token, cookie):
        self.runtimes[principal, space] = [name, token, cookie]

    def call(self, principal, space, method, args):
        if (principal, space) not in self.runtimes:
            return {'denied':True}
        if method not in {'session/create', 'session/list', 'session/rename'}:
            return {'denied':True}
        runtime = self.runtimes[principal, space]
        name, token, cookie = runtime
        status = http(name, '/', cookie)['status']
        if status == 401:
            cookie = runtime[2] = authenticate(name, token)
        elif status != 200:
            raise RuntimeError(f'Upstream unavailable: {status}')
        self.dispatches += 1
        return rpc(name, cookie, method, args)


try:
    print(f'Artifacts: {ROOT}', flush=True)
    baseline = health()
    record('production baseline', baseline == {'3081':200, '3080':401}, baseline)
    available = int(re.search(r'MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text())[1])
    if available < 1400 * 1024:
        raise RuntimeError(f'Insufficient spare memory for non-disruptive probe: {available // 1024} MiB')
    a, at, ah = launch('alice-zkxk')
    record('anonymous rejected', http(a, '/')['status'] == 401)
    ac = authenticate(a, at)
    record('server token exchange', http(a, '/', ac)['status'] == 200)
    record('invalid token rejected', http(a, '/?token=invalid')['status'] == 401)
    b, bt, bh = launch('bob-senyuan')
    bc = authenticate(b, bt)
    record('second instance authenticated', http(b, '/', bc)['status'] == 200)
    record('cross-instance cookie rejected', http(b, '/', ac)['status'] == 401)
    a_session = rpc(a, ac, 'session/create', {'request':{'cwd':'/home/probe/workspace'}})['sessionId']
    rpc(a, ac, 'session/rename', {'request':{'sessionId':a_session,'title':'Alice-only probe'}})
    b_session = rpc(b, bc, 'session/create', {'request':{'cwd':'/home/probe/workspace'}})['sessionId']
    rpc(b, bc, 'session/rename', {'request':{'sessionId':b_session,'title':'Bob-only probe'}})
    al = rpc(a, ac, 'session/list', {'_request':{}})['items']
    bl = rpc(b, bc, 'session/list', {'_request':{}})['items']
    record('real session list isolation', {x['sessionId'] for x in al} == {a_session}
           and {x['sessionId'] for x in bl} == {b_session}, {'aliceCount':len(al), 'bobCount':len(bl)})
    rpc(a, ac, 'settings/update', {'ns':'locale','patch':{'preference':'zh'}})
    rpc(b, bc, 'settings/update', {'ns':'locale','patch':{'preference':'en'}})
    av = rpc(a, ac, 'settings/describe', {})
    bv = rpc(b, bc, 'settings/describe', {})
    record('personal settings persisted separately', 'zh' in (ah/'dsh/settings.yaml').read_text()
           and 'en' in (bh/'dsh/settings.yaml').read_text())
    record('native settings namespaces', True, [x['ns'] for x in av['namespaces']])
    for name, cookie, own in [(a, ac, 'alice-zkxk'), (b, bc, 'bob-senyuan')]:
        own_file = http(name, '/api/file?path='+quote('/home/probe/workspace/identity.txt'), cookie)
        foreign = http(name, '/api/file?path='+quote('/root/liao/DepartmentKnowledgeBase/department-ai/.env'), cookie)
        secret = http(name, '/api/file?path='+quote('/home/probe/dsh/.credentials.yaml'), cookie)
        record(f'{own}: actual download isolation', own_file['status']==200 and own_file['body']==own
               and foreign['status'] != 200, {'own':own_file['status'],'hostFile':foreign['status']})
        record(f'{own}: native secret download exposure observed', secret['status']==200,
               {'status':secret['status'], 'implication':'Block arbitrary file access and move credentials outside agent-readable filesystem before production'})
    expired = client(a, {'op':'expired-cookie','cookie':ac})['cookie']
    record('correctly signed expired cookie rejected', http(a, '/', expired)['status']==401)
    broker = Broker()
    broker.register('alice', 'zkxk', a, at, expired)
    broker.register('bob', 'senyuan', b, bt, bc)
    record('broker rejects missing identity/foreign space/admin RPC',
           broker.call(None,'zkxk','session/list',{}) == {'denied':True}
           and broker.call('alice','senyuan','session/list',{}) == {'denied':True}
           and broker.call('alice','zkxk','settings/update',{}) == {'denied':True})
    renewed = broker.call('alice','zkxk','session/create',{'request':{'cwd':'/home/probe/workspace'}})
    record('automatic auth refresh before one mutation', bool(renewed.get('sessionId')) and broker.dispatches==1)
    denied_ws = client(a, {'op':'ws'})
    valid_ws = client(a, {'op':'ws','cookie':broker.runtimes['alice','zkxk'][2]})
    record('WebSocket unauthorized rejected', denied_ws['status']==401, denied_ws)
    record('WebSocket event stream with server-held cookie', valid_ws.get('ready') and valid_ws.get('pings',0)>=1, valid_ws)
    for name, identity, other_home in [(a, 'alice-zkxk', bh), (b, 'bob-senyuan', ah)]:
        result = client(name, {'op':'isolation', 'paths':[
            '/home/probe/workspace/identity.txt', str(other_home / 'workspace/identity.txt'),
            '/root/liao/DepartmentKnowledgeBase/department-ai/.env', '/var/run/docker.sock'],
            'writePaths':['/opt/harness/package.json'],
            'targets':[['127.0.0.1',5432], ['127.0.0.1',3081], ['172.17.0.1',5432]]})
        record(f'{identity}: filesystem/network boundary',
               result['uid'] == 10001 and result['reads']['/home/probe/workspace/identity.txt']['value'] == identity
               and all(not v['ok'] for k,v in result['reads'].items() if k != '/home/probe/workspace/identity.txt')
               and result['writes']['/opt/harness/package.json'] != 'allowed'
               and all(v != 'connected' for v in result['connections'].values()), result)
    record('container resource snapshot', True, command(['docker','stats','--no-stream','--format',
           '{{.Name}} {{.MemUsage}} {{.CPUPerc}}', a, b]))
    command(['docker','stop','--time','8',b], timeout=15)
    command(['docker','rm',b])
    CONTAINERS.remove(b)
    c, ct, ch = launch('alice-shared')
    cc = authenticate(c, ct)
    broker.register('alice','shared',c,ct,cc)
    c_session = broker.call('alice','shared','session/create',{'request':{'cwd':'/home/probe/workspace'}})['sessionId']
    broker.call('alice','shared','session/rename',{'request':{'sessionId':c_session,'title':'Shared-space-only probe'}})
    cl = broker.call('alice','shared','session/list',{'_request':{}})['items']
    al = broker.call('alice','zkxk','session/list',{'_request':{}})['items']
    record('same-user two-space route isolation', c_session in {x['sessionId'] for x in cl}
           and c_session not in {x['sessionId'] for x in al} and a_session not in {x['sessionId'] for x in cl})
    command(['docker','stop','--time','8',c], timeout=15)
    command(['docker','rm',c])
    CONTAINERS.remove(c)
    command(['docker','restart','--time','8',a], timeout=20)
    at2 = wait_ready(a, at)
    record('launch token changes on restart', at2 != at and http(a,'/?token='+at)['status']==401)
    record('persisted cookie survives restart', http(a,'/',ac)['status']==200)
    renewed_cookie = authenticate(a, at2)
    al = rpc(a, renewed_cookie, 'session/list', {'_request':{}})['items']
    record('session and settings survive restart', a_session in {x['sessionId'] for x in al}
           and 'zh' in (ah/'dsh/settings.yaml').read_text())
    broker.register('alice','zkxk',a,at2,expired)
    result = broker.call('alice','zkxk','session/list',{'_request':{}})
    record('broker refresh using new launch token', a_session in {x['sessionId'] for x in result['items']})
except Exception as e:
    record('probe exception', False, str(e))
finally:
    for name in reversed(CONTAINERS):
        try:
            state = json.loads(command(['docker','inspect','--format','{{json .State}}',name]))
            logs = re.sub(r'token=\S+', 'token=[REDACTED]', command(['docker','logs',name]))
            (ROOT / f'{name}.log').write_text(logs)
            if state['ExitCode']:
                record(f'{name}: exit diagnostic', False, logs[-4000:])
            record(f'{name}: runtime', not state['OOMKilled'], {k:state[k] for k in ['Running','OOMKilled','ExitCode']})
            command(['docker','stop','--time','8',name], timeout=15)
            command(['docker','rm',name])
        except Exception as e:
            record('cleanup error', False, str(e))
    record('production after probe', health() == baseline, health())
    (ROOT/'results.json').write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    print(f'Results retained: {ROOT}/results.json', flush=True)
    print('Temporary probe containers stopped and removed; isolated test data retained.', flush=True)
raise SystemExit(0 if all(x['ok'] for x in RESULTS) else 1)
