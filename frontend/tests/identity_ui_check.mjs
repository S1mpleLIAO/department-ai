import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const state={processes:[],documents:[],categories:[],purposes:[],skills:[],settings:{},services:{}}
const dom=await createDom({hash:'knowledge',state})
const {setIdentity,can,fileUrl,pageAllowed}=await import('../js/core/session.js')
const {renderKnowledge}=await import('../js/features/knowledge/index.js')
const member={user:{id:'member',companyId:'zkxk',superadmin:false,mustChangePassword:false},spaces:[{id:'zkxk',name:'中科信控'},{id:'shared',name:'部门共享'}],permissions:{zkxk:['knowledge.read','catalog.read','knowledge.create'],shared:['knowledge.read']}}
setIdentity(member)
renderKnowledge(()=>{})
assert.equal(dom.window.document.querySelector('#page-action').hidden,false,'新增开放草稿上传，不能直接发布')
assert.equal(dom.window.document.querySelector('#add-category').hidden,true,'只读目录不能创建')
dom.window.document.querySelector('[data-knowledge-view="published"]').click()
assert.equal(dom.window.document.querySelector('#add-category').hidden,true,'切换筛选不能恢复写按钮')
assert.equal(can('knowledge.read'),true)
assert.equal(can('knowledge.publish_direct'),false)
assert.equal(fileUrl('/api/documents/demo/source'),'/api/documents/demo/source?space=zkxk')
assert.equal(pageAllowed('settings'),false)
dom.window.sessionStorage.setItem('department-space','legacy')
setIdentity({user:{superadmin:true},spaces:[{id:'legacy'}],permissions:{}})
assert.equal(can('knowledge.read'),true)
assert.equal(can('knowledge.create'),false,'历史隔离空间不能显示创建按钮')
console.log('identity-ui-check: member action gates, filter rerender, download scope, 403 and legacy read-only passed')
dom.window.close()
