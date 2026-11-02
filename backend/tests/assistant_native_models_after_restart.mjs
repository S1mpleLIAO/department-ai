// Opt-in companion to assistant_native_models_probe.py, after the two native UI
// providers have been created and the two authenticated recycle requests pass.
// Reads only the disposable probe's private input, never acceptance credentials.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {chromium} from '/root/liao/DepartmentKnowledgeBase/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';

const root='.identity-state/native-models-probe/';
const input=JSON.parse(await fs.readFile(root+'browser-input.json','utf8'));
const progress=JSON.parse(await fs.readFile(root+'browser-progress.json','utf8'));
assert.ok(progress.recycled.length>=1);
assert.ok(progress.recycled.every(r=>r.status===200&&r.body.reclaimed&&r.body.restarted));
const browser=await chromium.launch({headless:true,executablePath:'/root/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',args:['--no-sandbox']});
const results=[];
try {
  for (const [i,u] of input.users.entries()) {
    const c=await browser.newContext();
    await c.addCookies([{name:'department_ai_'+u.space,value:u.cookie,url:u.origin,httpOnly:true,sameSite:'Lax'}]);
    if(!progress.recycled[i]) {
      // Resume an interrupted browser observation; repeat the real idle reclaim.
      const r=await c.request.post(u.origin+'/__probe/recycle',{headers:{Origin:u.origin},timeout:180000});
      const result={status:r.status(),body:await r.json()};
      assert.equal(result.status,200);assert.ok(result.body.reclaimed&&result.body.restarted);
      progress.recycled.push(result);
    }
    async function rpc(method,args) {
      const r=await c.request.post(u.origin+'/api/'+method,{headers:{Origin:u.origin},data:{type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}});
      assert.equal(r.status(),200);
      const b=await r.json();assert.equal(b.result.ok,true,JSON.stringify(b.result.error));return b.result.value;
    }
    const sessions=await rpc('session/list',{_request:{}});
    assert.equal(sessions.items.length,1);
    assert.equal(sessions.items[0].sessionId,progress.sessions[i]);
    assert.equal(sessions.items[0].projections.values.turnOutline.length,2);
    const creds=await rpc('credentials/describe',{refs:['NATIVE_PROBE_API_KEY']});
    assert.ok(!JSON.stringify(creds).includes(u.key));
    const p=await c.newPage();p.setDefaultTimeout(15000);
    await p.goto(u.origin+'/');
    await p.getByRole('button',{name:'Settings',exact:true}).click();
    await p.getByRole('button',{name:'Models',exact:true}).click();
    const own=i===0?'Private ZKXK':'Private SENYUAN';
    const other=i===0?'Private SENYUAN':'Private ZKXK';
    await p.getByText(own,{exact:true}).waitFor();
    assert.ok(!(await p.locator('body').innerText()).includes(other));
    await p.screenshot({path:root+'native-settings-'+u.space+'.png'});
    await p.getByRole('button',{name:'Close',exact:true}).click();
    await p.getByRole('treeitem',{name:new RegExp('NATIVE_OK '+u.space)}).click();
    const model=i===0?'probe-reason':'probe-fast';
    await p.getByRole('button',{name:'Select model, current '+model,exact:true}).waitFor();
    const before=await (await c.request.get(u.origin+'/__probe/results')).json();
    await p.locator('[contenteditable="true"]').fill('native UI after recycle '+u.space);
    await p.getByRole('button',{name:'Send message',exact:true}).click();
    let after;
    for(let n=0;n<30;n++) {
      after=await rpc('session/list',{_request:{}});
      const s=after.items[0];
      if(!s.running&&s.projections.values.turnOutline.length===3)break;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    const turns=after.items[0].projections.values.turnOutline;
    assert.equal(turns.length,3);
    assert.equal(turns[2].response,'NATIVE_OK '+u.space+' '+model);
    const calls=await (await c.request.get(u.origin+'/__probe/results')).json();
    assert.ok(calls.calls.length>before.calls.length);
    assert.ok(calls.calls.every(x=>x.user===u.user&&x.space===u.space&&x.credentialMatched));
    assert.deepEqual([...new Set(calls.calls.map(x=>x.model))].sort(),['probe-fast','probe-reason']);
    results.push({space:u.space,providerPreserved:true,secretRedacted:true,sessionPreserved:true,selectedModelPreserved:model,callWithoutRefillingKey:true,modelsUsed:['probe-fast','probe-reason']});
    await c.close();
  }
  await fs.writeFile(root+'browser-results.json',JSON.stringify({...progress,afterRestart:results},null,2));
  console.log(JSON.stringify({passed:true,results}));
} finally {await browser.close();}
