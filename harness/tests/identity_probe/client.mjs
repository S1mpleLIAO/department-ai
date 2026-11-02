// Disposable-instance probe client. Input/output are consumed by run.py;
// credentials must never be printed directly by the orchestrator.
import fs from 'node:fs/promises';
import net from 'node:net';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString());
if (input.op === 'http') {
  const response = await fetch(`http://127.0.0.1:39080${input.path}`, {
    method: input.method ?? 'GET', redirect: 'manual',
    headers: input.headers ?? {},
    ...(input.body === undefined ? {} : {body: JSON.stringify(input.body)}),
    signal: AbortSignal.timeout(15000),
  });
  const text = await response.text();
  process.stdout.write(JSON.stringify({status: response.status,
    cookie: response.headers.get('set-cookie'), location: response.headers.get('location'),
    body: text, bytes: text.length}));
} else if (input.op === 'isolation') {
  const reads = {};
  for (const path of input.paths) {
    try { reads[path] = {ok: true, value: await fs.readFile(path, 'utf8')}; }
    catch (e) { reads[path] = {ok: false, code: e.code}; }
  }
  const writes = {};
  for (const path of input.writePaths ?? []) {
    try { await fs.writeFile(path, 'probe'); writes[path] = 'allowed'; }
    catch (e) { writes[path] = e.code; }
  }
  const connections = {};
  for (const [host, port] of input.targets ?? []) {
    connections[`${host}:${port}`] = await new Promise(resolve => {
      const s = net.createConnection({host, port});
      const finish = value => {s.destroy(); resolve(value);};
      s.setTimeout(1500, () => finish('timeout'));
      s.once('error', e => finish(e.code));
      s.once('connect', () => finish('connected'));
    });
  }
  process.stdout.write(JSON.stringify({uid: process.getuid(), reads, writes, connections}));
} else if (input.op === 'expired-cookie') {
  // Deliberately expired, correctly signed cookie made ONLY with the disposable home's key.
  const {createHmac} = await import('node:crypto');
  const yaml = await import('/opt/harness/packages/settings/settings-file/node_modules/yaml/dist/index.js');
  const data = yaml.parse(await fs.readFile('/home/probe/dsh/.credentials.yaml', 'utf8'));
  const find = obj => {
    if (!obj || typeof obj !== 'object') return undefined;
    if (obj.version === 1 && typeof obj.secret === 'string') return obj.secret;
    return Object.values(obj).map(find).find(Boolean);
  };
  const secret = find(data);
  if (!secret) throw new Error('Disposable signing key not found');
  const body = Buffer.from(JSON.stringify({version:1, authority:'127.0.0.1:39080',
    issuedAt:Date.now()-120000, expiresAt:Date.now()-60000})).toString('base64url');
  const sig = createHmac('sha256', Buffer.from(secret, 'base64url')).update(body).digest('base64url');
  process.stdout.write(JSON.stringify({cookie: `${input.cookie.split('=')[0]}=v1.${body}.${sig}`}));
} else if (input.op === 'ws') {
  const {default: WebSocket} = await import('/opt/harness/packages/api/gateway/node_modules/ws/wrapper.mjs');
  const result = await new Promise(resolve => {
    const ws = new WebSocket('ws://127.0.0.1:39080/api/remote.mux', {
      headers: {Cookie: input.cookie ?? '', Origin:'http://127.0.0.1:39080'},
    });
    let ready = false, pings = 0, finished = false;
    const finish = result => {if (finished) return; finished = true; clearTimeout(timer); ws.terminate(); resolve(result);};
    const timer = setTimeout(() => finish({ready, pings, status: ready ? 101 : 0}), 5500);
    ws.on('open', () => ws.send(JSON.stringify({type:'open',streamId:'probe-events',endpoint:'$events',payload:{args:{}}})));
    ws.on('ping', () => pings++);
    ws.on('message', data => {const frame=JSON.parse(data.toString()); if(frame.type==='item' && frame.value?.type==='ready') ready=true;});
    ws.on('unexpected-response', (_, res) => finish({ready:false,status:res.statusCode}));
    ws.on('error', error => finish({ready, status:0, error:error.message}));
  });
  process.stdout.write(JSON.stringify(result));
}
