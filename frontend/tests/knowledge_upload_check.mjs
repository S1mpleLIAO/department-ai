import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const chunking = {
  mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80,
  parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30,
  cleanWhitespace: true, removeUrlsEmails: false,
}
const purposes = [
  {
    id: 'generation-template', name: '生成模板', canGenerateTemplate: true,
    chunkBody: false, inheritChunking: true, chunkSettings: {}, documentCount: 0,
  },
  {
    id: 'reference-knowledge', name: '参考知识', canGenerateTemplate: false,
    chunkBody: true, inheritChunking: true, chunkSettings: {}, documentCount: 0,
  },
  {
    id: 'template-and-reference', name: '模板＋参考知识', canGenerateTemplate: true,
    chunkBody: true, inheritChunking: true, chunkSettings: {}, documentCount: 0,
  },
]
const state = {
  processes: [], categories: [{ id: 'contracts', name: '合同', parentId: null }], purposes,
  documents: [], skills: [], settings: { chunking }, services: {},
}
const requests = []
const dom = await createDom({
  hash: 'knowledge',
  state,
  onRequest: (url, options) => requests.push({ url, method: options.method || 'GET', body: options.body }),
})
requests.length = 0

const metadata = await import('../js/features/knowledge/upload-metadata.js')
const chunks = await import('../js/features/knowledge/upload-chunks.js')

for (const name of ['metadataFormHtml', 'applyMetadataSuggestion', 'collectMetadata', 'validateMetadata', 'selectedPurpose', 'togglePurposeFields']) {
  assert.equal(typeof metadata[name], 'function', `metadata module 应导出 ${name}`)
}
for (const name of ['chunkPanelHtml', 'renderChunkPreview', 'collectPreviewChunks', 'hasEnabledChunk', 'renderIndexPlan']) {
  assert.equal(typeof chunks[name], 'function', `chunks module 应导出 ${name}`)
}

async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 0))
  }
  assert.fail(message)
}

function response(payload, ok = true) {
  return { ok, json: async () => structuredClone(payload) }
}

let previewSequence = 0
let analyzeFails = false
let indexFails = false
const workflowFetch = async (url, options = {}) => {
  const current = { url: String(url), method: options.method || 'GET', body: options.body }
  requests.push(current)
  if (current.url === '/api/state') return response(state)
  if (current.url === '/api/knowledge/preview') {
    previewSequence += 1
    return response({ id: `preview/${previewSequence}`, fileName: '合同.docx', characters: 3 })
  }
  if (current.url.endsWith('/analyze')) {
    if (analyzeFails) return response({ detail: 'AI 服务暂不可用' }, false)
    return response({
      id: `preview/${previewSequence}`,
      metadata: {
        title: 'AI 合同模板', documentType: '合同', summary: 'AI 摘要', keywords: ['采购', '合同'],
        suggestedPurposeId: 'generation-template', templateFamily: '采购合同', templateVariant: '标准版',
        version: 'V2.0', applicableScenario: '采购', outline: ['第一章'],
      },
    })
  }
  if (current.url.endsWith('/rechunk')) {
    return response({
      id: `preview/${previewSequence}`, characters: 3,
      chunks: [{ index: 0, parentIndex: null, sectionPath: '第一章', content: 'ABC', tokenCount: 3, enabled: true }],
    })
  }
  if (current.url.endsWith('/index')) {
    if (indexFails) return response({ detail: '索引服务暂不可用' }, false)
    return response({ saved: true })
  }
  if (current.method === 'DELETE') return response({ deleted: true })
  return response({})
}
dom.window.fetch = globalThis.fetch = workflowFetch

function attachFile() {
  const input = document.querySelector('#knowledge-file')
  const file = new dom.window.File(['ABC'], '合同.docx', {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })
  Object.defineProperty(input, 'files', { configurable: true, value: [file] })
  input.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
}

document.querySelector('#page-action').click()
assert.equal(document.querySelector('#document-purpose').value, '')
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false)
assert.equal(document.querySelectorAll('[data-upload-step]').length, 4, '应渲染四个真实步骤面板')

const basePlan = '<b>将建立的索引</b><span>文档目录索引（标题、摘要、关键词和正文摘要）</span>'
assert.equal(chunks.renderIndexPlan(purposes[0]), `${basePlan}<span>整份模板推荐索引</span><span>正文不切块，完整正文仍会保存</span>`, '生成模板应只建立整份模板索引')
assert.equal(chunks.renderIndexPlan(purposes[1]), `${basePlan}<span>正文分块索引</span>`, '参考知识应建立正文分块索引')
assert.equal(chunks.renderIndexPlan(purposes[2]), `${basePlan}<span>整份模板推荐索引</span><span>正文分块索引</span>`, '组合用途应同时建立两类索引')

attachFile()
document.querySelector('#parse-document').click()
await waitFor(() => requests.at(-1)?.url === '/api/knowledge/preview', '应发送正文解析请求')
assert.deepEqual(JSON.parse(requests.at(-1).body), {
  fileName: '合同.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', fileBase64: 'QUJD',
})
await waitFor(() => document.querySelector('[data-upload-step="reviewing-metadata"]').hidden === false, '解析后应进入属性确认')

document.querySelector('#analyze-metadata').click()
await waitFor(() => requests.at(-1)?.url.endsWith('/analyze'), '应发送独立 AI 分析请求')
await waitFor(() => document.querySelector('#document-purpose').value === 'generation-template', 'AI 建议应预填用途')
assert.equal(document.querySelector('#document-title').dataset.aiSuggested, 'true', 'AI 填入字段应带建议标记')
assert.equal(document.querySelector('#document-purpose').dataset.aiSuggested, 'true', 'AI 建议用途应带建议标记')
assert.equal(document.querySelector('[data-upload-step="reviewing-index"]').hidden, true, 'AI 不得自动跳过人工确认')

const analyzeCount = requests.filter(({ url }) => url.endsWith('/analyze')).length
attachFile()
await waitFor(() => requests.at(-1)?.method === 'DELETE', '文件变化应删除旧预览')
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false, '文件变化应重置到第一步')
document.querySelector('#parse-document').click()
await waitFor(() => requests.at(-1)?.url === '/api/knowledge/preview', '新文件应重新解析')
await waitFor(() => document.querySelector('[data-upload-step="reviewing-metadata"]').hidden === false, '重新解析后应进入属性确认')

document.querySelector('#document-title').value = ''
document.querySelector('#document-purpose').value = ''
document.querySelector('#metadata-continue').click()
assert.equal(document.activeElement, document.querySelector('#document-title'), '属性校验应聚焦第一个无效字段')
assert.equal(document.querySelector('#document-title').getAttribute('aria-invalid'), 'true')

document.querySelector('#document-id').value = 'knowledge-contract'
document.querySelector('#document-title').value = '手工合同模板'
document.querySelector('#document-purpose').value = 'generation-template'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
document.querySelector('#template-family').value = '采购合同'
const manualContinueStart = requests.length
document.querySelector('#metadata-continue').click()
await waitFor(() => document.querySelector('[data-upload-step="reviewing-index"]').hidden === false, '手填属性应进入索引预览')
assert.equal(requests.slice(manualContinueStart).some(({ url }) => url.endsWith('/analyze')), false, '手填路径不得调用 AI 分析')
assert.equal(requests.slice(manualContinueStart).some(({ url }) => url.endsWith('/rechunk')), false, '生成模板用途不得调用重新切块')
assert.equal(requests.filter(({ url }) => url.endsWith('/analyze')).length, analyzeCount, '第二条路径不应新增 AI 请求')

const earlyIndexCount = requests.filter(({ url }) => url.endsWith('/index')).length
assert.equal(document.querySelector('#dialog-save').hidden, true, '索引预览阶段不得显示最终入库操作')
document.querySelector('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(requests.filter(({ url }) => url.endsWith('/index')).length, earlyIndexCount, '只有最终确认阶段可以提交索引')

document.querySelector('#index-continue').click()
assert.equal(document.querySelector('[data-upload-step="confirming"]').hidden, false, '索引确认后应进入最终确认')
assert.equal(document.querySelector('#dialog-save').hidden, false)
assert.equal(document.querySelector('#dialog-save').textContent, '确认入库')

indexFails = true
document.querySelector('#dialog-save').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/index')).length === earlyIndexCount + 1, '应尝试最终索引')
await waitFor(() => document.querySelector('#dialog-save').disabled === false && document.querySelector('#dialog-save').textContent === '确认入库', '保存失败应恢复最终确认和重试操作')
assert.equal(document.querySelector('[data-upload-step="confirming"]').hidden, false, '保存失败应停留在最终确认')
assert.equal(document.querySelector('#document-title').value, '手工合同模板', '保存失败应保留表单输入')

indexFails = false
document.querySelector('#dialog-save').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/index')).length === earlyIndexCount + 2, '失败后应允许重试')
const indexRequest = requests.filter(({ url }) => url.endsWith('/index')).at(-1)
assert.equal(indexRequest.url, '/api/knowledge/previews/preview%2F2/index')
assert.deepEqual(JSON.parse(indexRequest.body), {
  id: 'knowledge-contract', title: '手工合同模板', purposeId: 'generation-template', documentType: '', keywords: [], outline: [],
  categoryId: '', status: 'effective', summary: '', templateFamily: '采购合同', templateVariant: '', version: 'V1.0',
  applicableScenario: '', chunks: [],
}, '最终入库应保持既有确认请求体')
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => document.querySelector('#editor-dialog').open === false, '成功入库后应关闭弹窗')

document.querySelector('#page-action').click()
attachFile()
document.querySelector('#parse-document').click()
await waitFor(() => document.querySelector('[data-upload-step="reviewing-metadata"]').hidden === false, '参考资料应完成解析')
document.querySelector('#document-title').value = '参考合同'
document.querySelector('#document-purpose').value = 'reference-knowledge'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
document.querySelector('#metadata-continue').click()
await waitFor(() => requests.at(-1)?.url.endsWith('/rechunk'), '参考知识应生成分块')
await waitFor(() => document.querySelectorAll('#chunk-preview .chunk-card').length === 1, '应渲染分块预览')
assert.equal(document.querySelector('[data-upload-step="reviewing-index"]').hidden, false)

document.querySelector('[data-upload-nav="reviewing-metadata"]').click()
assert.equal(document.querySelector('#document-title').value, '参考合同', '返回已完成步骤应保留输入')
document.querySelector('#document-purpose').value = 'template-and-reference'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
assert.equal(document.querySelectorAll('#chunk-preview .chunk-card').length, 0, '用途变化必须失效旧分块预览')

document.querySelector('#document-title').value = '保留的人工标题'
document.querySelector('#template-family').value = '保留的模板家族'
analyzeFails = true
document.querySelector('#analyze-metadata').click()
await waitFor(() => requests.at(-1)?.url.endsWith('/analyze'), '应发送失败场景的 AI 请求')
await waitFor(() => document.querySelector('#metadata-error').hidden === false, 'AI 失败应显示内联错误')
assert.equal(document.querySelector('#document-title').value, '保留的人工标题', 'AI 失败不得清空标题')
assert.equal(document.querySelector('#document-purpose').value, 'template-and-reference', 'AI 失败不得清空用途')
assert.equal(document.querySelector('#template-family').value, '保留的模板家族', 'AI 失败不得清空模板属性')

console.log('knowledge-upload-check: ok')
