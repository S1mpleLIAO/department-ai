"""Real native department tools, isolated fixture DB/home and deterministic model.
Checks script execution, file tools/download, live skill filtering and persistence.
"""
import asyncio,base64,json,os,socket,shlex
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import httpx,psycopg,uvicorn
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from assistant_pool_probe import creds,STATE,rpc,until
from app.core.database import create_pool
from app.features.identity.service import HASHER,login,authenticate
from app.features.assistant.runtime import Manager,PrivateSocketServer
from app.features.assistant.activity import activity
from app.features.assistant.auth import issue,redeem
from app.features.assistant.resources import call
from app.features.assistant import gateway

async def main():
    uid=str(uuid4());tag='restore-'+uid[:8];pw=uuid4().hex+'X1'
    db=create_pool(creds['appDsn']);db.open(wait=True)
    manager=server=task=None;captured=[];checks=[];runtime=None
    names=[tag,tag+'-foreign',tag+'-disabled']
    script="const fs=require('fs');fs.writeFileSync('skill-result.txt','APPROVED_SCRIPT_OK');console.log('SCRIPT_EXECUTED');"
    data={'skill':{'name':tag,'description':'Synthetic approved file generator','instructions':'Read references/input.txt then run scripts/generate.cjs with node. Output skill-result.txt in the task workspace.'},'resources':[
        {'path':'scripts/generate.cjs','contentBase64':base64.b64encode(script.encode()).decode()},
        {'path':'references/input.txt','contentBase64':base64.b64encode(b'SYNTHETIC_REFERENCE').decode()}]}
    def check(name):checks.append(name);print('PASS',name,flush=True)
    try:
        with psycopg.connect(creds['adminDsn']) as c:
            c.execute("INSERT INTO users(id,username,display_name,password_hash,company_id,must_change_password) VALUES(%s,%s,'部门工具临时验证',%s,'zkxk',false)",(uid,tag,HASHER.hash(pw)))
            c.execute('INSERT INTO permission_groups(id,name,actions) VALUES(%s,%s,%s)',(tag,tag,Jsonb(['assistant.use','skills.use','skills.source_read'])))
            c.execute("INSERT INTO user_space_grants(user_id,space_id,group_id) VALUES(%s,'zkxk',%s)",(uid,tag))
            for name,space,enabled in ((names[0],'zkxk',True),(names[1],'senyuan',True),(names[2],'zkxk',False)):
                copy={**data,'skill':{**data['skill'],'name':name}}
                c.execute("INSERT INTO review_submissions(id,space_id,owner_id,kind,title,draft,status,published_id) VALUES(%s,%s,%s,'skills',%s,%s,'published',%s)",(name,space,uid,name,Jsonb(copy),name))
                c.execute('INSERT INTO skill_publications(id,space_id,submission_id,data,enabled) VALUES(%s,%s,%s,%s,%s)',(name,space,name,Jsonb(copy),enabled))
        token,_,_=login(db,tag,pw,'restore-test','restore-test');p=authenticate(db,token)[0]
        stub=FastAPI()
        @stub.post('/v1/chat/completions')
        async def model(request:Request):
            body=await request.json()
            primary=any(x.get('function',{}).get('name')=='department_context_get' for x in body.get('tools',[]))
            if primary:captured.append(body)
            n=len(captured)-1
            folder=next(iter((runtime.root/'home/workspace').glob('skill-*')),None) if runtime else None
            local='/home/assistant/workspace/'+folder.name if folder else '/not-ready'
            steps=[
                ('skill',{'name':tag}),
                ('department_skill_prepare',{'id':tag}),
                ('bash',{'command':'node '+shlex.quote(local+'/scripts/generate.cjs'),'description':'Execute the approved synthetic skill script'}),
                ('write',{'file_path':'notes.txt','content':'ORIGINAL_NOTE'}),
                ('read',{'file_path':'notes.txt'}),
                ('edit',{'file_path':'notes.txt','old_string':'ORIGINAL_NOTE','new_string':'EDITED_NOTE'}),
                ('glob',{'pattern':'*.txt','path':'/home/assistant/workspace'}),
                ('grep',{'pattern':'EDITED_NOTE','path':'/home/assistant/workspace'}),
                ('todo_write',{'todos':[{'content':'Execute approved skill and deliver files','status':'completed'}]}),
                ('bash',{'command':"node -e \"const fs=require('fs'); if(fs.existsSync('/root/liao')||fs.existsSync('/home/other'))process.exit(3);try{fs.writeFileSync('/home/assistant/outside-workspace','bad');process.exit(4)}catch(e){console.log('ISOLATION_OK')}\"",'description':'Check personal workspace and host isolation'}),
                ('skill',{'name':names[1]}),
                ('department_skill_prepare',{'id':names[2]}),
            ]
            async def stream():
                def chunk(delta,finish=None):return 'data: '+json.dumps({'id':'restore','object':'chat.completion.chunk','created':0,'model':'department-test','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n'
                yield chunk({'role':'assistant'})
                if primary and n<len(steps):
                    name,args=steps[n]
                    yield chunk({'tool_calls':[{'index':0,'id':'restore-'+str(n),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]});yield chunk({},'tool_calls')
                else:yield chunk({'content':'RESTORE_DONE'});yield chunk({},'stop')
                yield 'data: [DONE]\n\n'
            return StreamingResponse(stream(),media_type='text/event-stream')
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
        os.environ['DEPARTMENT_AI_MODEL_URL']=f'http://127.0.0.1:{sock.getsockname()[1]}/v1';os.environ['DEPARTMENT_AI_MODEL_KEY']='synthetic-only'
        server=PrivateSocketServer(uvicorn.Config(stub,log_level='error',access_log=False,lifespan='off'));task=asyncio.create_task(server.serve(sockets=[sock]));await until(lambda:server.started,5)
        with TemporaryDirectory(prefix='department-restore-') as folder:
            os.environ['DEPARTMENT_AI_STATE_DIR']=folder;manager=Manager(db,['department-test'])
            runtime=await manager.get(p,'zkxk')
            origin='http://127.0.0.1:3182';os.environ['DEPARTMENT_AI_ORIGINS']=json.dumps({'zkxk':origin})
            gateway.app.state.manager=manager;gateway.app.state.pool=db;gateway.app.state.origins={'zkxk':origin}
            gateway.app.state.settings=type('Settings',(),{'auth_origin':origin})()
            cookie=redeem(db,issue(db,p,'zkxk')['ticket'],origin)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url=origin,cookies={'department_ai_zkxk':cookie},headers={'Origin':origin},timeout=200) as browser:
                async def api(name,args):
                    r=await browser.post('/api/'+name,json={'type':'client-request','rpcId':str(uuid4()),'method':name,'payload':{'args':args}})
                    assert r.status_code==200,(name,r.text);v=r.json()['result'];assert v['ok'],v;return v.get('value')
                sid=(await api('session/create',{'request':{'cwd':'/home/assistant/workspace','agentPreset':'department'}}))['sessionId']
                compact=await api('commands/execute',{'agentId':sid,'line':'/compact','submittedAttachments':[]})
                assert 'No compactable history' in json.dumps(compact),compact
                check('native manual compact command reaches the engine through guarded gateway')
                await api('session/prompt',{'request':{'sessionId':sid,'requestId':str(uuid4()),'mode':'queue','content':[{'type':'text','text':'Run the approved synthetic skill, create/edit/read/search the test files, check sandbox, and deny other-company and disabled skills. All files are disposable in this test workspace.'}]}})
                try:await until(lambda:len(captured)>=13,150)
                finally:
                    (STATE/'department-capabilities-trace.private.json').write_text(json.dumps(captured,ensure_ascii=False));(STATE/'department-capabilities-trace.private.json').chmod(0o600)
                async with asyncio.timeout(30):
                    while any((await activity(runtime)).values()):await asyncio.sleep(.2)
                first=captured[0];schema={x['function']['name'] for x in first['tools']}
                assert {'bash','skill','read','write','edit','glob','grep','todo_write','ask_user_question'}<=schema,schema
                initial=json.dumps(first['messages'],ensure_ascii=False)
                assert tag in initial and names[1] not in initial and names[2] not in initial
                check('native skill catalog includes own approved skill, excludes foreign and disabled')
                outputs=[m for m in captured[-1]['messages'] if m.get('role')=='tool'];text=json.dumps(outputs,ensure_ascii=False)
                assert 'SCRIPT_EXECUTED' in text and 'SYNTHETIC_REFERENCE' not in initial,text[-1000:]
                for name,expected in [('skill-result.txt','APPROVED_SCRIPT_OK'),('notes.txt','EDITED_NOTE')]:
                    r=await browser.get('/api/file',params={'path':'/home/assistant/workspace/'+name,'download':'1'})
                    assert r.status_code==200 and r.text==expected,(name,r.status_code,r.text[:200])
                    assert 'attachment' in r.headers.get('content-disposition','')
                check('native skill load, resource preparation, shell execution, file read/write/edit and authenticated downloads')
                # Search must actually succeed, not merely be present in the tool registry.
                by_id={m.get('tool_call_id'):m for m in outputs}
                for index in (6,7,8):
                    result=json.dumps(by_id['restore-'+str(index)],ensure_ascii=False)
                    assert not any(x in result for x in ('ENOENT','isError": true','failed to','Error:')),result
                assert 'EDITED_NOTE' in json.dumps(by_id['restore-7'])
                check('native filename/content search and task checklist execute successfully')
                assert 'ISOLATION_OK' in text and not (runtime.root/'home/outside-workspace').exists()
                assert 'unknown or no longer available' in json.dumps(by_id['restore-10'])
                assert '找不到可用的已发布技能' in json.dumps(by_id['restore-11'],ensure_ascii=False)
                check('native sandbox blocks outside-workspace writes; foreign and disabled skill loads denied')
                r=await browser.get('/api/file',params={'path':'/config/patch.yml'});assert r.status_code in (403,404)
                # Actual runtime stop/restart retains the test conversation and generated files.
                await runtime.stop();manager.items.pop(runtime.key,None)
                runtime=await manager.get(p,'zkxk')
                rows=await api('session/list',{'_request':{}});assert sid in {x['sessionId'] for x in rows['items']}
                r=await browser.get('/api/file',params={'path':'/home/assistant/workspace/skill-result.txt','download':'1'});assert r.text=='APPROVED_SCRIPT_OK'
                check('restart preserves existing conversation and generated file/download')
                with psycopg.connect(creds['adminDsn']) as c:c.execute('UPDATE permission_groups SET actions=%s WHERE id=%s',(Jsonb(['assistant.use','skills.use']),tag))
                fresh=authenticate(db,token)[0]
                assert call(db,fresh,'zkxk','department_skill_get',{'id':tag})['name']==tag
                try:call(db,fresh,'zkxk','department_skill_prepare',{'id':tag})
                except HTTPException as e:assert e.status_code==403
                else:raise AssertionError('source permission bypassed')
                r=await browser.get('/api/file',params={'path':'/home/assistant/workspace/skill-result.txt'});assert r.status_code in (403,409)
                check('use-only can load instructions but cannot export source; changed authorization invalidates old runtime')
            await manager.close();manager=None
        (STATE/'department-capabilities-results.json').write_text(json.dumps({'passed':True,'checks':checks,'model':'deterministic; real Harness, tools and isolated containers'},ensure_ascii=False,indent=2))
    finally:
        if manager:await manager.close()
        if server:server.should_exit=True
        if task:await task
        with psycopg.connect(creds['adminDsn']) as c:
            c.execute('DELETE FROM skill_publications WHERE id=ANY(%s)',(names,));c.execute('DELETE FROM review_submissions WHERE id=ANY(%s)',(names,))
            c.execute('UPDATE users SET active=false,permission_version=permission_version+1 WHERE id=%s',(uid,));c.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s',(uid,))
            c.execute('DELETE FROM user_space_grants WHERE user_id=%s',(uid,));c.execute('DELETE FROM permission_groups WHERE id=%s',(tag,))
        db.close()
if __name__=='__main__':asyncio.run(main())
