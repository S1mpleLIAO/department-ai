import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const state={processes:[],documents:[],categories:[],purposes:[],skills:[],settings:{},services:{}}
const dom=await createDom({state})
const {document,Event}=dom.window
const {permissionTree,bindPermissionTree}=await import('../js/features/identity/permissions.js')
const actions=[{module:'skills',name:'技能',items:['source_read','use','create'].map(a=>({id:'skills.'+a,name:a}))},
  {module:'knowledge',name:'知识库',items:['read','create','review','publish_direct'].map(a=>({id:'knowledge.'+a,name:a}))}]
const root=document.createElement('div')
document.body.append(root)
root.innerHTML=permissionTree(actions)
bindPermissionTree(root)
const box=id=>root.querySelector(`[value="${id}"]`)
box('skills.use').click()
assert.equal(box('skills.source_read').checked,false,'using a skill must not grant its source')
box('skills.create').click()
assert.equal(box('skills.source_read').checked,true,'editing needs source access')
box('skills.source_read').click()
assert.equal(box('skills.create').checked,false)
assert.equal(box('skills.use').checked,true,'removing source access must preserve standalone skill use')
assert.equal(root.querySelector('[data-module="skills"]').indeterminate,true)
box('knowledge.create').click()
assert.equal(box('knowledge.read').checked,true)
assert.equal(box('knowledge.publish_direct').checked,false,'create never implies bypass-review publishing')
root.remove()

const overview={users:[{id:'member',displayName:'测试成员',username:'member',companyId:'zkxk',active:true,revision:2}],userTotal:1,pageSize:25,
  companies:[{id:'zkxk',name:'中科信控'},{id:'senyuan',name:'森远股份'}],spaces:[{id:'zkxk',name:'中科信控'},{id:'senyuan',name:'森远股份'},{id:'shared',name:'部门共享'}],
  groups:[{id:'contributor',name:'内容提交人员',description:'创建草稿',actions:['knowledge.read','knowledge.create']},
    {id:'reader',name:'只读人员',description:'仅查看',actions:['knowledge.read']}],
  grants:[{user_id:'member',space_id:'zkxk',group_id:'contributor'},{user_id:'member',space_id:'shared',group_id:'reader'}],actions}
const writes=[]
dom.window.fetch=globalThis.fetch=async(url,options={})=>{
  if(options.method==='PUT')writes.push(JSON.parse(options.body))
  return {ok:true,json:async()=>structuredClone(String(url).startsWith('/api/admin/overview')?overview:state)}
}
const {renderAdmin}=await import('../js/features/identity/admin.js')
dom.window.history.replaceState(null,'','#admin')
await renderAdmin()
assert.equal(document.querySelectorAll('[data-admin-tab]').length,4)
document.querySelector('[data-user-grants]').click()
const scope=document.querySelector('#grant-scope')
assert.equal(scope.value,'zkxk')
assert.equal(document.querySelector('#grant-effective [value="knowledge.create"]').checked,true)
scope.value='senyuan';scope.dispatchEvent(new Event('change'))
assert.equal(document.querySelectorAll('[data-grant-group]:checked').length,0,'another company starts without grants')
document.querySelector('[data-grant-group="reader"]').click()
assert.equal(document.querySelector('#grant-effective [value="knowledge.create"]').checked,false,'permissions do not leak across spaces')
scope.value='zkxk';scope.dispatchEvent(new Event('change'))
assert.equal(document.querySelector('[data-grant-group="contributor"]').checked,true,'switching preserves selections')
scope.value='shared';scope.dispatchEvent(new Event('change'))
assert.equal(document.querySelectorAll('[data-grant-group]:checked').length,1)
document.querySelector('#dialog-save').click()
assert.match(document.querySelector('#confirm-detail').textContent,/森远股份/)
document.querySelector('#confirm-dialog button[value="confirm"]').click()
await new Promise(r=>setTimeout(r,450))
assert.deepEqual(writes[0].grants,[{spaceId:'zkxk',groupId:'contributor'},{spaceId:'senyuan',groupId:'reader'},{spaceId:'shared',groupId:'reader'}])
document.querySelector('[data-admin-tab="groups"]').click()
await new Promise(r=>setTimeout(r,0))
assert.match(document.querySelector('#admin-panel').textContent,/配置功能/)
document.querySelector('[data-group-edit="contributor"]').click()
assert.equal(document.querySelectorAll('.permission-module').length,2)
assert.equal(document.querySelector('[value="knowledge.publish_direct"]').checked,false)
console.log('permission-admin-check: skill/source separation, dependency tree, company-scoped union, grant persistence, cross-company confirmation and module editor passed')
dom.window.close()
