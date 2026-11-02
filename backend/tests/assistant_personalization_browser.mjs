import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {chromium} from '/root/liao/DepartmentKnowledgeBase/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
const root='.identity-state/personalization-live/';
const d=JSON.parse(await fs.readFile(root+'browser-input.json'));
const b=await chromium.launch({executablePath:'/root/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',args:['--no-sandbox']});
const results=[];
try {
 for(const [i,u] of d.users.entries()) {
  const c=await b.newContext();await c.addCookies([{name:'department_ai_'+u.space,value:u.cookie,url:u.origin}]);
  async function rpc(method,args) {const r=await c.request.post(u.origin+'/api/'+method,{headers:{Origin:u.origin},data:{type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}});assert.equal(r.status(),200,method);const out=await r.json();assert.ok(out.result.ok,JSON.stringify(out.result.error));return out.result.value;}
  const p=await c.newPage();p.setDefaultTimeout(20000);await p.goto(u.origin);await p.getByRole('button',{name:'Settings',exact:true}).waitFor();
  await p.waitForTimeout(1500);if(await p.getByRole('button',{name:'Continue',exact:true}).count())await p.getByRole('button',{name:'Continue',exact:true}).click();
  await p.getByRole('button',{name:'Settings',exact:true}).click();await p.getByRole('button',{name:'Models',exact:true}).click();
  const own='Private '+u.space.toUpperCase();
  if(!(await p.getByText(own,{exact:true}).count())) {
   await p.getByRole('button',{name:'Add a custom provider',exact:true}).click();
   await p.getByRole('textbox',{name:'Provider ID',exact:true}).fill('native-live');
   await p.getByRole('textbox',{name:'Display name',exact:true}).fill(own);
   await p.getByRole('textbox',{name:'Base URL',exact:true}).fill(d.baseURL);
   await p.getByRole('textbox',{name:'API key',exact:true}).fill(d.key);
   await p.getByRole('button',{name:'Add model',exact:true}).click();
   await p.getByRole('textbox',{name:'Model ID 1',exact:true}).fill(d.model);
   await p.getByRole('textbox',{name:'Display name 1',exact:true}).fill('My '+d.model);
   await p.getByRole('button',{name:'Create provider',exact:true}).click();
  }
  await p.getByText(own,{exact:true}).waitFor();
  assert.ok(!(await p.locator('body').innerText()).includes('Private '+d.users[1-i].space.toUpperCase()));
  await p.screenshot({path:root+'models-'+u.space+'.png'});
  await p.getByRole('button',{name:'Close',exact:true}).click();await p.getByRole('button',{name:'New session',exact:true}).last().click();
  if((await p.getByRole('button',{name:'Choose workspace',exact:true}).innerText()).trim()==='Choose workspace'){await p.getByRole('button',{name:'Choose workspace',exact:true}).click();await p.getByRole('button',{name:'Open',exact:true}).click();}
  await p.getByRole('button',{name:/^(部门助手|Standard mode)$/}).click();
  await p.getByRole('menuitem',{name:/Standard mode/}).click();
  await p.getByRole('button',{name:'Standard mode',exact:true}).waitFor();
  await p.getByRole('button',{name:/Select model, current/}).click();
  await p.getByRole('menuitem',{name:/^Model /}).click();await p.getByRole('menuitemradio',{name:'My '+d.model,exact:true}).click();
  await p.locator('[contenteditable="true"]').fill('Use the bash tool to run node -e '+JSON.stringify("require('fs').writeFileSync('native-check.txt','PRIVATE_NATIVE_OK_"+u.space+"');console.log('SHELL_OK')")+'. Then reply PRIVATE_NATIVE_OK. This is an isolated acceptance check; do not modify anything else.');
  const before=await rpc('session/list',{_request:{}});const counts=new Map(before.items.map(x=>[x.sessionId,x.projections.values.turnOutline.length]));
  await p.getByRole('button',{name:'Send message',exact:true}).click();
  let rows,session;
  for(let n=0;n<120;n++) {
    rows=await rpc('session/list',{_request:{}});
    session=rows.items.find(x=>x.projections?.values?.turnOutline?.length>(counts.get(x.sessionId)||0));
    if(session&&!session.running&&session.projections.values.turnOutline.at(-1).response)break;
    await p.waitForTimeout(1000);
  }
  assert.ok(session&&!session.running,'native turn did not finish');
  console.log(u.space,'TURN',JSON.stringify(session.projections.values));
  const file=await c.request.get(u.origin+'/api/file',{params:{path:'/home/assistant/workspace/native-check.txt',download:'1'}});
  console.log(u.space,'DOWNLOAD',file.status());
  if(file.status()!==200)console.log('PAGE',await p.locator('body').ariaSnapshot());
  assert.equal(file.status(),200);assert.equal(await file.text(),'PRIVATE_NATIVE_OK_'+u.space);
  results.push({space:u.space,sessionId:session.sessionId,standardPreset:true,personalModel:true,shellFileDownload:true});
  await p.screenshot({path:root+'coding-'+u.space+'.png'});
  await fs.writeFile(root+'progress.json',JSON.stringify(results,null,2));
  await c.close();
 }
} finally {await b.close();}
