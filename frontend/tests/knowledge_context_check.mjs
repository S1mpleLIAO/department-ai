import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const processes = [{
  id: 'procurement', name: '项目采购', description: '采购流程',
  steps: [{
    id: 'contract', name: '采购合同', objective: '签订合同',
    requiredInputs: [], requiredOutputs: [], completionCriteria: [], instructions: '',
  }],
}]
const scope = await import('../js/features/knowledge/scope.js')
for (const name of ['scopeFieldsHtml', 'bindScopeFields', 'collectScope', 'validateScope', 'applyScope', 'scopeLabel']) {
  assert.equal(typeof scope[name], 'function', `scope module 应导出 ${name}`)
}
const detail = {
  id: 'purchase-contract', title: '采购合同模板', originalName: '采购合同.docx', categoryId: 'contracts',
  purposeId: 'generation-template', purposeName: '生成模板', documentType: '合同', status: 'effective',
  keywords: ['采购', '合同'], isGenerationTemplate: true, isReferenceKnowledge: true,
  documentIndexed: true, chunkIndexed: true, chunkCount: 1, templateFamily: '采购合同', templateVariant: '标准版',
  version: 'V2.0', scopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract',
  applicableScenario: '', summary: '采购合同模板摘要', updatedAt: '2026-09-03T00:00:00Z',
  outline: ['第一章'], parsedText: '合同正文',
  chunks: [{ id: 'chunk-1', index: 0, parentIndex: null, sectionPath: '第一章', content: '合同正文', tokenCount: 4, enabled: true }],
}
const state = {
  processes,
  categories: [{ id: 'contracts', name: '合同', parentId: null }],
  purposes: [{
    id: 'generation-template', name: '生成模板', canGenerateTemplate: true,
    chunkBody: false, inheritChunking: true, chunkSettings: {}, documentCount: 1,
  }],
  documents: [detail], skills: [],
  settings: { chunking: { mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80, parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30, cleanWhitespace: true, removeUrlsEmails: false } },
  services: {},
}
const requests = []
const dom = await createDom({
  hash: 'knowledge', state,
  onRequest: (url, options) => requests.push({ url, method: options.method || 'GET', body: options.body }),
})
requests.length = 0

function response(payload, ok = true) {
  return { ok, json: async () => structuredClone(payload) }
}

dom.window.fetch = globalThis.fetch = async (url, options = {}) => {
  const current = { url: String(url), method: options.method || 'GET', body: options.body }
  requests.push(current)
  if (current.url === '/api/documents/purchase-contract' && current.method === 'GET') return response(detail)
  if (current.url === '/api/documents/purchase-contract' && current.method === 'PUT') return response({ saved: true })
  if (current.url === '/api/state') return response(state)
  return response({})
}

async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 0))
  }
  assert.fail(message)
}

document.querySelector('.view-document').click()
await waitFor(() => document.querySelector('#edit-document'), '应打开流程范围文档详情')
assert.match(document.querySelector('.detail-grid').textContent, /适用范围项目采购 \/ 采购合同/, '详情应显示流程和步骤名称')
document.querySelector('#edit-document').click()
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => document.querySelector('#edit-scope-process'), '应打开带适用范围的文档编辑器')
assert.equal(document.querySelector('#edit-scope-process').checked, true, '编辑器应回填流程范围')
assert.equal(document.querySelector('#edit-process').value, 'procurement')
assert.equal(document.querySelector('#edit-step').value, 'contract')
document.querySelector('#edit-scope-task').click()
document.querySelector('#edit-task-scenario').value = '编写设计方案'
document.querySelector('#dialog-save').click()
await waitFor(() => requests.some(({ method }) => method === 'PUT'), '编辑文档应发送 PUT 请求')
const updateRequest = requests.find(({ method }) => method === 'PUT')
assert.deepEqual(JSON.parse(updateRequest.body), {
  title: '采购合同模板', categoryId: 'contracts', status: 'effective', documentType: '合同', keywords: ['采购', '合同'],
  outline: ['第一章'], templateFamily: '采购合同', templateVariant: '标准版', version: 'V2.0',
  scopeType: 'task', applicableProcessId: '', applicableStepId: '', applicableScenario: '编写设计方案',
  summary: '采购合同模板摘要',
}, '文档编辑应提交归一化范围并保留既有元数据')

document.body.innerHTML = scope.scopeFieldsHtml('test', processes, { scopeType: '' })
scope.bindScopeFields('test', processes)
assert.ok(document.querySelector('fieldset.scope-fieldset > legend'), '适用范围应使用原生分组语义')
assert.equal(document.querySelector('#test-scope-global').labels.length, 1, '范围选项应有真实标签')
assert.equal(scope.validateScope('test').id, 'test-scope-global', '未确认范围应聚焦第一个选项')

document.querySelector('#test-scope-task').click()
assert.equal(document.querySelector('#test-task-fields').hidden, false)
assert.equal(document.querySelector('#test-process-fields').hidden, true)
assert.equal(scope.validateScope('test').id, 'test-task-scenario')
document.querySelector('#test-task-scenario').value = '编写设计方案'
assert.deepEqual(scope.collectScope('test'), {
  scopeType: 'task', applicableProcessId: '', applicableStepId: '',
  applicableScenario: '编写设计方案',
})

document.querySelector('#test-scope-process').click()
document.querySelector('#test-process').value = 'procurement'
document.querySelector('#test-process').dispatchEvent(new Event('change', { bubbles: true }))
assert.equal(document.querySelector('#test-step').value, '', '切换流程必须清空旧步骤')
document.querySelector('#test-step').value = 'contract'
assert.deepEqual(scope.collectScope('test'), {
  scopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract',
  applicableScenario: '',
})

scope.applyScope('test', { suggestedScopeType: 'global' }, processes)
assert.equal(document.querySelector('#test-scope-global').checked, true, 'AI 可建议全局范围')
scope.applyScope('test', { suggestedScopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract' }, processes)
assert.equal(document.querySelector('#test-scope-process').checked, true, '有效流程建议应回填')
assert.equal(document.querySelector('#test-process').value, 'procurement')
assert.equal(document.querySelector('#test-step').value, 'contract')
scope.applyScope('test', { suggestedScopeType: 'process', applicableProcessId: 'missing', applicableStepId: 'contract' }, processes)
assert.equal(document.querySelector('input[name="test-scope-type"]:checked'), null, '无效流程建议不得选择范围')

assert.equal(scope.scopeLabel({ scopeType: 'global' }, processes), '全局通用')
assert.equal(scope.scopeLabel({ scopeType: 'task', applicableScenario: '编写设计方案' }, processes), '独立任务 / 编写设计方案')
assert.equal(scope.scopeLabel({ scopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract' }, processes), '项目采购 / 采购合同')
console.log('knowledge-context-check: ok')
