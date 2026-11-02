import fs from 'node:fs/promises';import assert from 'node:assert/strict';
import {chromium} from '/root/liao/DepartmentKnowledgeBase/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
const root='.identity-state/personalization-live/';const d=JSON.parse(await fs.readFile(root+'browser-input.json'));
const progress=JSON.parse(await fs.readFile(root+'progress.json'));
const b=await chromium.launch({executablePath:'/root/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',args:['--no-sandbox']});
try {
 const contexts=await Promise.all(d.users.map(async u=>{const c=await b.newContext();await c.addCookies([{name:'department_ai_'+u.space,value:u.cookie,url:u.origin}]);return c;}));
 async function rpc(i,method,args) {const u=d.users[i];const r=await contexts[i].request.post(u.origin+'/api/'+method,{headers:{Origin:u.origin},data:{type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}});assert.equal(r.status(),200,method);const body=await r.json();assert.ok(body.result.ok,JSON.stringify(body.result.error));return body.result.value;}
 for(let i=0;i<2;i++) {
  const u=d.users[i];
  await rpc(i,'credentials/set',{ref:'ISOLATION_MARKER_API_KEY',value:'isolated-'+u.space});
  const other=await rpc(1-i,'credentials/describe',{refs:['ISOLATION_MARKER_API_KEY']});
  if(i===0&&!process.env.SKIP_RECYCLE)assert.equal(other.ISOLATION_MARKER_API_KEY.configured,false);
 }
 const before=[];
 for(const u of d.users){const file=u.root+'/home/dsh/credentials.json';const candidates=await fs.readdir(u.root+'/home/dsh');console.log('PRIVATE_FILES',u.space,candidates.filter(x=>/credential|setting/.test(x)));before.push(await fs.readFile(u.root+'/home/dsh/settings.yaml','utf8'));}
 const recycled=process.env.SKIP_RECYCLE?[]:await Promise.all(d.users.map(async(u,i)=>{const r=await contexts[i].request.post(u.origin+'/__probe/recycle',{headers:{Origin:u.origin},timeout:240000});assert.equal(r.status(),200,await r.text());console.log('RECYCLED',u.space);return await r.json();}));
 const results=[];
 for(let i=0;i<2;i++) {
  const u=d.users[i];assert.equal(await fs.readFile(u.root+'/home/dsh/settings.yaml','utf8'),before[i]);
  const rows=await rpc(i,'session/list',{_request:{}});const saved=rows.items.find(x=>x.sessionId===progress[i].sessionId);
  assert.ok(saved);assert.equal(saved.projections.values.modelSelection.next.provider,'native-live');assert.equal(saved.projections.values.agentPreset,'standard');
  const download=await contexts[i].request.get(u.origin+'/api/file',{params:{path:'/home/assistant/workspace/native-check.txt',download:'1'}});assert.equal(download.status(),200);assert.equal(await download.text(),'PRIVATE_NATIVE_OK_'+u.space);
  const cross=await contexts[1-i].request.get(u.origin+'/');assert.equal(cross.status(),401);
  const c=contexts[i],p=await c.newPage();p.setDefaultTimeout(20000);await p.goto(u.origin);await p.getByRole('button',{name:'Settings',exact:true}).click();await p.getByRole('button',{name:'Models',exact:true}).click();await p.getByText('Private '+u.space.toUpperCase(),{exact:true}).waitFor();
  assert.ok(!(await p.locator('body').innerText()).includes('Private '+d.users[1-i].space.toUpperCase()));
  await p.getByRole('button',{name:'Close',exact:true}).click();
  // Continue the same session through the authenticated API after the native UI check.
  const old=saved.projections.values.turnOutline.length;
  await rpc(i,'session/prompt',{request:{sessionId:saved.sessionId,requestId:crypto.randomUUID(),mode:'queue',content:[{type:'text',text:'Reply exactly RESTART_OK.'}]}});
  let after;
  for(let n=0;n<120;n++){after=(await rpc(i,'session/list',{_request:{}})).items.find(x=>x.sessionId===saved.sessionId);if(!after.running&&after.projections.values.turnOutline.length>old&&after.projections.values.turnOutline.at(-1).response)break;await p.waitForTimeout(1000);}
  assert.match(after.projections.values.turnOutline.at(-1).response,/RESTART_OK/);
  results.push({space:u.space,configurationPreserved:true,sessionPreserved:true,downloadPreserved:true,realModelCallAfterRecycle:true,crossCompanyCookieDenied:true});
 }
 await fs.writeFile(root+'restart-results.json',JSON.stringify({results,recycled},null,2));console.log('PASS',JSON.stringify(results));
} finally {await b.close();}
