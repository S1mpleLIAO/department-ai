/** Public-origin native settings transport keeps RPC on its authenticated origin. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const calls=[],origin='https://ai-zkxk.supercomputing7.xyz';
const context=vm.createContext({
 URL,location:{origin,href:origin+'/'},
 fetch:async (...args)=>{calls.push(args);return {ok:true};},
 addEventListener:()=>{},
});
vm.runInContext(fs.readFileSync('harness/identity/runtime-status.js','utf8'),context);
const hook=context.__DSH_TRANSPORT__;
assert.equal(hook.ownsHost,true);
const body='{"method":"settings/describe"}';
await hook.fetch(new URL(origin+'/api/settings/describe'),{method:'POST',body,credentials:'include',redirect:'follow'});
assert.equal(calls.length,1);assert.equal(calls[0][0].href,origin+'/api/settings/describe');
assert.equal(calls[0][1].body,body);assert.equal(calls[0][1].credentials,'same-origin');assert.equal(calls[0][1].redirect,'error');
for(const url of ['https://ai-senyuan.supercomputing7.xyz/api/settings/describe','http://127.0.0.1:3080/api/settings/describe',origin+'/bootstrap']){
 await assert.rejects(hook.fetch(new URL(url),{}));
}
assert.equal(calls.length,1);
console.log('PASS native public settings transport; cross-origin calls and redirects refused');

const clientScript = fs.readFileSync('harness/identity/space-path.js', 'utf8');
const gateway = 'http://127.0.0.1:23182';
function tab(space, storage) {
  const base = '/s/' + space + '/';
  const document = { baseURI: gateway + base, addEventListener() {} };
  const window = {
    departmentScope: [base, 'same-user'], localStorage: storage, sessionStorage: storage,
    fetch: url => url.href, WebSocket: class { constructor(url) { this.url = url.href; } }
  };
  vm.runInNewContext(clientScript, { window, document, URL, Request, location: new URL(document.baseURI) });
  return window;
}
const storage = Object.create({
  getItem(key) { return this[key] ?? null; }, setItem(key, value) { this[key] = String(value); },
  removeItem(key) { delete this[key]; }
});
const first = tab('zkxk', storage), second = tab('ca123456789', storage);
for (const [client, space] of [[first,'zkxk'], [second,'ca123456789']]) {
  client.localStorage.setItem('current-session', space);
  assert.equal(client.fetch('/api/session/list'), gateway + '/s/' + space + '/api/session/list');
  assert.equal(new client.WebSocket('ws://127.0.0.1:23182/api/remote.mux').url,
               'ws://127.0.0.1:23182/s/' + space + '/api/remote.mux');
}
assert.equal(first.localStorage.getItem('current-session'), 'zkxk');
second.localStorage.clear();
assert.equal(first.localStorage.length, 1);
assert.equal(second.localStorage.length, 0);
assert.throws(() => first.fetch('/s/ca123456789/api/file'), /公司空间/);
console.log('PASS shared gateway tab routing and storage isolation');
