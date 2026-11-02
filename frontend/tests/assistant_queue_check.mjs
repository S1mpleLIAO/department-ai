import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync('harness/identity/starting.html','utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
let checks=0;
function context(){
 const elements=Object.fromEntries(['#status','#cancel','#retry'].map(k=>[k,{hidden:true,disabled:false,textContent:''}]));
 const requests=[],timers=[],redirects=[];
 const c={document:{querySelector:k=>elements[k]},AbortSignal:{timeout:()=>({})},
 fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
 setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},
 location:{replace:url=>redirects.push(url)}};
 vm.runInNewContext(source,c);
 return {elements,requests,timers,redirects};
}
const flush=()=>new Promise(r=>setImmediate(r));
const respond=(req,data,ok=true)=>req.resolve({ok,json:async()=>data});
{
 const c=context();respond(c.requests[0],{state:'queued',position:2,capacity:4,reason:'capacity'});
 await flush();assert.match(c.elements['#status'].textContent,/第 2 位/);assert.equal(c.elements['#cancel'].hidden,false);
 c.timers[0]();const late=c.requests[1];
 const cancelled=c.elements['#cancel'].onclick();respond(c.requests[2],{cancelled:true});await cancelled;
 respond(late,{ready:true});await flush();
 assert.equal(c.redirects.length,0);assert.match(c.elements['#status'].textContent,/已取消/);checks++;
}
{
 const c=context();respond(c.requests[0],{state:'starting',capacity:4});await flush();
 assert.equal(c.elements['#cancel'].hidden,true);assert.match(c.elements['#status'].textContent,/正在启动/);
 c.timers[0]();respond(c.requests[1],{ready:true});await flush();assert.deepEqual(c.redirects,['/']);checks++;
}
{
 const c=context();respond(c.requests[0],{detail:'授权已变化'},false);await flush();
 assert.equal(c.elements['#retry'].hidden,false);assert.match(c.elements['#status'].textContent,/授权已变化/);
 c.elements['#retry'].onclick();assert.equal(c.requests[1].url,'/ready?retry=1');checks++;
}
new vm.Script(fs.readFileSync('harness/identity/runtime-status.js','utf8'));
console.log(checks+' queue UI state/race checks passed');

