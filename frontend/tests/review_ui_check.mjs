import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const state={processes:[],documents:[],categories:[],purposes:[],skills:[],settings:{},services:{}}
const dom=await createDom({hash:'processes',state,asyncDialogClose:true})
const {document,Event}=dom.window
const {setIdentity}=await import('../js/core/session.js')
const {openProcessEditor}=await import('../js/features/processes/editor.js')
const {renderReviews}=await import('../js/features/reviews/index.js')
const {indexKnowledge}=await import('../js/features/knowledge/upload-api.js')
const member={user:{id:'author',companyId:'zkxk',superadmin:false,mustChangePassword:false},spaces:[{id:'zkxk'}],
  permissions:{zkxk:['processes.read','processes.create','knowledge.read','knowledge.create','skills.source_read','skills.create']}}
const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,10))}throw Error('UI wait timed out')}
let requests=[],row=null,fail=false
dom.window.fetch=globalThis.fetch=async(url,options={})=>{
  const path=String(url),body=options.body?JSON.parse(options.body):null
  requests.push({path,body,method:options.method||'GET'})
  let result=state
  if(path==='/api/reviews'&&body?.kind==='processes'){
    row={id:body.id,kind:'processes',title:body.data.name,data:body.data,status:'draft',revision:1,version:0,
      author:'测试成员',owner_id:'author',updatedAt:new Date().toISOString(),feedback:'',publish_error:'',history:[]}
    result=row
  }else if(path.startsWith('/api/reviews?'))result={items:row?[row]:[],total:row?1:0,page:0,pageSize:20}
  else if(path==='/api/reviews/'+row?.id)result=row
  else if(path.endsWith('/submit')){row={...row,status:'submitted',revision:2,version:1};result=row}
  else if(path.endsWith('/approve')){row={...row,status:'approved',revision:3};result=row}
  if(fail&&path.endsWith('/publish'))return {ok:false,status:409,json:async()=>({detail:'状态已变化，请刷新'})}
  return {ok:true,status:200,json:async()=>structuredClone(result)}
}
setIdentity(member)
openProcessEditor(undefined,()=>{})
document.querySelector('#process-name').value='新增审核流程'
document.querySelector('[data-key="name"]').value='检查'
document.querySelector('[data-key="objective"]').value='确认供应商'
assert.equal(document.querySelector('#dialog-save').textContent,'保存草稿')
document.querySelector('#dialog-save').click()
await wait(()=>row&&!document.querySelector('#editor-dialog').open)
assert.ok(requests.some(r=>r.path==='/api/reviews'&&r.body.kind==='processes'))
assert.ok(!requests.some(r=>r.path==='/api/processes'),'成员不能走直接发布接口')
await renderReviews()
await wait(()=>document.querySelector('[data-review-id]'))
document.querySelector('[data-review-id]').click()
await wait(()=>document.querySelector('[data-review-action="submit"]'))
assert.equal(document.querySelector('[data-review-action="approve"]'),null)
document.querySelector('[data-review-action="submit"]').click()
await wait(()=>document.querySelector('#confirm-dialog').open)
document.querySelector('#confirm-dialog [value="confirm"]').click()
await wait(()=>row.status==='submitted'&&!document.querySelector('#editor-dialog').open)
await renderReviews()
document.querySelector('[data-review-id]').click()
await wait(()=>document.querySelector('#editor-dialog').open)
assert.equal(document.querySelector('[data-review-action="edit"]'),null,'待审核禁止修改')
await new Promise(r=>setTimeout(r,200))
document.querySelector('#editor-dialog .dialog-close').click()
await wait(()=>!document.querySelector('#editor-dialog').open&&!document.querySelector('#editor-dialog').closePromise)
setIdentity({...member,user:{...member.user,id:'reviewer'},permissions:{zkxk:['processes.read','processes.review','processes.publish']}})
await renderReviews()
document.querySelector('[data-review-id]').click()
await wait(()=>document.querySelector('[data-review-action="reject"]'))
document.querySelector('[data-review-action="reject"]').click()
assert.match(document.querySelector('#review-error').textContent,/原因/)
assert.equal(document.activeElement.id,'review-reason')
document.querySelector('[data-review-action="approve"]').click()
await wait(()=>document.querySelector('#confirm-dialog').open)
document.querySelector('#confirm-dialog [value="confirm"]').click()
await wait(()=>row.status==='approved'&&!document.querySelector('#editor-dialog').open)
await renderReviews()
document.querySelector('[data-review-id]').click()
await wait(()=>document.querySelector('[data-review-action="publish"]'))
fail=true
document.querySelector('[data-review-action="publish"]').click()
await wait(()=>document.querySelector('#confirm-dialog').open)
document.querySelector('#confirm-dialog [value="confirm"]').click()
await wait(()=>document.querySelector('#review-error').textContent.includes('状态已变化'))
assert.equal(document.querySelector('#editor-dialog').open,true,'失败保留当前审核详情')
assert.equal(document.querySelector('[data-review-action="publish"]').disabled,false)
setIdentity(member)
await indexKnowledge('preview-test',{title:'知识草稿',purposeId:'reference',categoryId:'',chunks:[{content:'正文'}]})
assert.ok(requests.some(r=>r.path==='/api/reviews'&&r.body.kind==='knowledge'&&r.body.previewId==='preview-test'))
assert.ok(!requests.some(r=>r.path.includes('/previews/preview-test/index')))
console.log('review-ui-check: draft creation, submit, immutable pending UI, rejection validation, approval, conflict recovery and upload routing passed')
dom.window.close()
