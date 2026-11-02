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
