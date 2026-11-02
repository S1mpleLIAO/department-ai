import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const state={processes:[],documents:[],categories:[],purposes:[{id:'reference-knowledge',name:'参考知识',chunkBody:true,canGenerateTemplate:false}],skills:[],settings:{},services:{}}
const dom=await createDom({hash:'reviews',state,asyncDialogClose:true})
const {document}=dom.window
const {setIdentity}=await import('../js/core/session.js')
const {beginEdit}=await import('../js/features/reviews/edit-entry.js')
const {renderReviews}=await import('../js/features/reviews/index.js')
const identity={user:{id:'editor',companyId:'zkxk',superadmin:false,mustChangePassword:false},spaces:[{id:'zkxk'}],
  permissions:{zkxk:['processes.read','processes.edit_any','knowledge.read','knowledge.edit_any','skills.source_read','skills.edit_any']}}
setIdentity(identity)
const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,10))}throw Error('UI wait timed out')}
const payloads={
  processes:{id:'process-1',name:'返修流程',description:'旧要求',steps:[{id:'step-1',name:'登记',objective:'核对保修',requiredInputs:[],requiredOutputs:[],completionCriteria:[],instructions:''}]},
  knowledge:{resourceId:'doc-1',fileName:'原文.txt',parsedText:'原正文',metadata:{id:'doc-1',title:'旧文档',purposeId:'reference-knowledge',categoryId:null,outline:[],chunks:[{content:'原分块',enabled:true,parentIndex:null,sectionPath:''}]}},
  skills:{skill:{name:'skill-1',description:'旧说明',instructions:'旧技能规则',enabled:true},resources:[{path:'references/old.txt',contentBase64:'b2xk'}]}
}
let row,requests=[],saved,failOnce=true
dom.window.fetch=globalThis.fetch=async(url,options={})=>{
  const path=String(url),body=options.body?JSON.parse(options.body):null,method=options.method||'GET'
  requests.push({path,body,method})
  let result=state
  if(path==='/api/reviews/edits'){
    if(failOnce){failOnce=false;return {ok:false,status:503,json:async()=>({detail:'暂时不可用'})}}
    row={id:body.id,kind:body.kind,targetId:body.targetId,title:'修改审核测试',data:structuredClone(payloads[body.kind]),base:structuredClone(payloads[body.kind]),
      owner_id:'editor',author:'编辑者',status:'draft',revision:1,version:0,history:[],updatedAt:new Date().toISOString(),feedback:'',publish_error:''}
    result=row
  }else if(path.startsWith('/api/reviews?'))result={items:[row],total:1,page:0}
  else if(path==='/api/reviews/'+row.id&&method==='PUT'){saved=body;row={...row,data:body.data,revision:2};result=row}
  else if(path==='/api/reviews/'+row.id)result=row
  return {ok:true,status:200,json:async()=>structuredClone(result)}
}
await beginEdit('processes','process-1')
assert.equal(document.querySelector('#editor-dialog').open,false)
await beginEdit('processes','process-1')
assert.equal(requests[0].body.id,requests[1].body.id,'uncertain create reuses request ID')
assert.equal(document.querySelector('#dialog-save').textContent,'保存草稿')
document.querySelector('#process-description').value='新要求'
document.querySelector('#dialog-save').click()
await wait(()=>saved&&!document.querySelector('#editor-dialog').open)
assert.equal(saved.data.id,'process-1')
assert.equal(saved.data.description,'新要求')
assert.ok(!requests.some(r=>r.path.startsWith('/api/processes')&&r.method==='PUT'))
await renderReviews()
document.querySelector('[data-review-id]').click()
await wait(()=>document.querySelector('[data-review-action="edit"]'))
assert.ok(document.querySelector('[data-review-action="submit"]'),'edit capability can submit without create capability')
assert.match(document.querySelector('#dialog-content').textContent,/修改前/)
assert.match(document.querySelector('#dialog-content').textContent,/旧要求/)
assert.match(document.querySelector('#dialog-content').textContent,/新要求/)
document.querySelector('#editor-dialog .dialog-close').click()
await wait(()=>!document.querySelector('#editor-dialog').open&&!document.querySelector('#editor-dialog').closePromise)
saved=null
await beginEdit('knowledge','doc-1')
assert.equal(document.querySelector('#document-id').readOnly,true)
document.querySelector('#document-title').value='新标题'
document.querySelector('#dialog-save').click()
await wait(()=>saved&&!document.querySelector('#editor-dialog').open)
assert.equal(saved.data.id,'doc-1')
assert.equal(saved.data.title,'新标题')
assert.ok(!requests.some(r=>r.path.startsWith('/api/documents')&&r.method==='PUT'))
saved=null
await beginEdit('skills','skill-1')
assert.equal(document.querySelector('#skill-name').readOnly,true)
document.querySelector('#skill-instructions').value='新技能规则'
document.querySelector('.resource-remove').click()
document.querySelector('#dialog-save').click()
await wait(()=>saved&&!document.querySelector('#editor-dialog').open)
assert.equal(saved.data.skill.name,'skill-1')
assert.equal(saved.data.skill.instructions,'新技能规则')
assert.deepEqual(saved.data.resources,[])
assert.ok(!requests.some(r=>r.path.startsWith('/api/skills')&&['PUT','DELETE'].includes(r.method)))
const normalFetch=globalThis.fetch
let release
dom.window.fetch=globalThis.fetch=async(url,options={})=>{
  if(String(url)==='/api/reviews/edits')await new Promise(resolve=>{release=resolve})
  return normalFetch(url,options)
}
const opening=beginEdit('processes','process-1')
await wait(()=>release)
dom.window.location.hash='#dashboard'
release()
await opening
assert.equal(document.querySelector('#editor-dialog').open,false,'late draft response must not open over another page')
console.log('review-edit-ui-check: retry, edit permission, three draft editors, comparison, stale navigation and no direct publication passed')
dom.window.close()
