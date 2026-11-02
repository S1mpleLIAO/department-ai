import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const dom=await createDom({hash:'assistant',state:{services:{}}})
const {setIdentity,pageAllowed}=await import('../js/core/session.js')
const {renderAssistant}=await import('../js/features/assistant.js')
const user={user:{id:'alice',companyId:'zkxk',superadmin:false},spaces:[{id:'zkxk'}],permissions:{zkxk:['assistant.use']},capabilities:{assistant:true}}
setIdentity(user)
assert.equal(pageAllowed('assistant'),true)
let sent
dom.window.HTMLFormElement.prototype.submit=function(){sent={action:this.action,method:this.method,target:this.target,ticket:this.elements.ticket.value}}
globalThis.fetch=async()=>({ok:true,json:async()=>({action:'http://127.0.0.1:3182/bootstrap',ticket:'private-test-ticket'})})
await renderAssistant()
assert.equal(sent.method,'post')
assert(document.querySelector('.assistant-mode').textContent.includes('部门助手 / 通用编程'))
assert.equal(document.querySelector('.assistant-mode button, .assistant-mode select'),null)
assert.equal(sent.ticket,'private-test-ticket')
assert(!sent.action.includes('ticket'))
assert.equal(document.querySelector('#assistant-host iframe').name,sent.target)
assert.equal(document.querySelector('input[name=ticket]'),null)
assert(!sessionStorage.getItem('private-test-ticket'))
document.querySelector('#assistant-host').replaceChildren()
globalThis.fetch=async()=>({ok:false,status:503,json:async()=>({detail:'个人 AI 服务尚未配置'})})
await renderAssistant()
assert(document.querySelector('[role=alert]').textContent.includes('尚未配置'))
assert(document.querySelector('#assistant-retry'))
document.querySelector('#assistant-host').replaceChildren()
let resolve
globalThis.fetch=()=>new Promise(r=>{resolve=r})
const pending=renderAssistant()
location.hash='#knowledge'
resolve({ok:true,json:async()=>({action:'http://127.0.0.1:3182/bootstrap',ticket:'late'})})
await pending
assert.equal(document.querySelector('#assistant-host iframe'),null)
setIdentity({...user,permissions:{}})
assert.equal(pageAllowed('assistant'),false)
console.log('assistant-ui-check: permission, POST ticket, cleanup, failure retry and stale navigation passed')
dom.window.close()
