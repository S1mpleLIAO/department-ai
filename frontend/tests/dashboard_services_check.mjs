import assert from 'node:assert/strict'
import {createDom} from './helpers/dom.mjs'
const value={processes:[],documents:[],categories:[],purposes:[],skills:[],settings:{},services:{}}
const dom=await createDom({state:value})
const {replaceState}=await import('../js/core/state.js')
const {renderDashboard}=await import('../js/features/dashboard.js')
for (const available of [false,true]) {
  replaceState({...value,services:{database:available,docling:available,siliconflow:available,metadata:available}})
  renderDashboard()
  const badges=[...document.querySelectorAll('.service-badge')]
  assert.equal(badges.length,4)
  assert.ok(badges.every(b=>b.classList.contains(available?'ok':'off')))
  assert.equal(badges[1].textContent,available?'Docling：可用':'Docling：不可用')
  assert.equal(badges[2].textContent,available?'Embedding / Rerank：已配置':'Embedding / Rerank：未配置')
  assert.equal(badges[3].textContent,available?'AI 元数据分析：已配置':'AI 元数据分析：未配置')
  assert.match(document.querySelector('#content').textContent,/实际可用性以分析、入库和检索结果为准/)
}
dom.window.close()
console.log('dashboard-service-check: configured/unconfigured labels and health/config distinction passed')
