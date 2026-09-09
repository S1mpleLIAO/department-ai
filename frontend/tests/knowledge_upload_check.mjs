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
const responseHolds = new Map()
function holdNextResponse(kind) {
  let release
  responseHolds.set(kind, new Promise(resolve => { release = resolve }))
  return release
}
async function waitForRelease(kind) {
  const hold = responseHolds.get(kind)
  if (!hold) return
  responseHolds.delete(kind)
  await hold
}
const workflowFetch = async (url, options = {}) => {
  const current = { url: String(url), method: options.method || 'GET', body: options.body }
  requests.push(current)
  if (current.url === '/api/state') return response(state)
  if (current.url === '/api/categories') {
    await waitForRelease('category')
    const category = { id: 'single-created', ...JSON.parse(options.body) }
    return response({ category })
  }
  if (current.url === '/api/knowledge/preview') {
    previewSequence += 1
    await waitForRelease('preview')
    return response({ id: `preview/${previewSequence}`, fileName: '合同.docx', characters: 3 })
  }
  if (current.url.endsWith('/analyze')) {
    await waitForRelease('analyze')
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
    await waitForRelease('rechunk')
    return response({
      id: `preview/${previewSequence}`, characters: 3,
      chunks: [{ index: 0, parentIndex: null, sectionPath: '第一章', content: 'ABC', tokenCount: 3, enabled: true }],
    })
  }
  if (current.url.endsWith('/index')) {
    await waitForRelease('index')
    if (indexFails) return response({ detail: '索引服务暂不可用' }, false)
    return response({ saved: true })
  }
  if (current.method === 'DELETE') return response({ deleted: true })
  return response({})
}
dom.window.fetch = globalThis.fetch = workflowFetch

function attachFile(name = '合同.docx') {
  const input = document.querySelector('#knowledge-file')
  const file = new dom.window.File(['ABC'], name, {
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

document.querySelector('#document-id').value = 'INVALID ID'
document.querySelector('#document-title').value = '手工合同模板'
document.querySelector('#document-purpose').value = 'generation-template'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
document.querySelector('#template-family').value = '采购合同'
const invalidIdRequestCount = requests.length
document.querySelector('#metadata-continue').click()
assert.equal(document.querySelector('[data-upload-step="reviewing-metadata"]').hidden, false, '无效文档 ID 不得离开属性步骤')
assert.equal(document.activeElement, document.querySelector('#document-id'), '属性步骤应聚焦无效文档 ID')
assert.equal(document.querySelector('#document-id').getAttribute('aria-invalid'), 'true')
assert.equal(requests.length, invalidIdRequestCount, '无效文档 ID 不得发送下游请求')

document.querySelector('#document-id').value = 'knowledge-contract'
const manualContinueStart = requests.length
document.querySelector('#metadata-continue').click()
await waitFor(() => document.querySelector('[data-upload-step="reviewing-index"]').hidden === false, '手填属性应进入索引预览')
assert.equal(requests.slice(manualContinueStart).some(({ url }) => url.endsWith('/analyze')), false, '手填路径不得调用 AI 分析')
assert.equal(requests.slice(manualContinueStart).some(({ url }) => url.endsWith('/rechunk')), false, '生成模板用途不得调用重新切块')
assert.equal(requests.filter(({ url }) => url.endsWith('/analyze')).length, analyzeCount, '第二条路径不应新增 AI 请求')

const earlyIndexCount = requests.filter(({ url }) => url.endsWith('/index')).length
assert.equal(document.querySelector('#dialog-save').hidden, true, '索引预览阶段不得显示最终入库操作')
assert.equal(document.querySelector('#dialog-save').disabled, true, '非最终确认阶段还应禁用保存按钮')
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
const releaseIndex = holdNextResponse('index')
const successfulPreviewDeleteCount = requests.filter(({ url, method }) => method === 'DELETE' && url === '/api/knowledge/previews/preview%2F2').length
document.querySelector('#dialog-save').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/index')).length === earlyIndexCount + 2, '失败后应允许重试')
const indexRequest = requests.filter(({ url }) => url.endsWith('/index')).at(-1)
assert.equal(indexRequest.url, '/api/knowledge/previews/preview%2F2/index')
assert.deepEqual(JSON.parse(indexRequest.body), {
  id: 'knowledge-contract', title: '手工合同模板', purposeId: 'generation-template', documentType: '', keywords: [], outline: [],
  categoryId: null, status: 'effective', summary: '', templateFamily: '采购合同', templateVariant: '', version: 'V1.0',
  applicableScenario: '', chunks: [],
}, '最终入库应保持既有确认请求体')
const closeButtons = [...document.querySelectorAll('#editor-dialog .dialog-close')]
assert.equal(closeButtons.every(button => button.disabled), true, '保存中应禁用所有关闭按钮')
closeButtons.at(-1).click()
document.querySelector('#editor-dialog').dispatchEvent(new dom.window.Event('cancel', { cancelable: true }))
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(document.querySelector('#editor-dialog').open, true, '保存中取消按钮和 Escape 都不得关闭弹窗')
assert.equal(requests.filter(({ url, method }) => method === 'DELETE' && url === '/api/knowledge/previews/preview%2F2').length, successfulPreviewDeleteCount, '保存中不得删除正在索引的预览')
releaseIndex()
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => document.querySelector('#editor-dialog').open === false, '成功入库后应关闭弹窗')
assert.equal(requests.filter(({ url, method }) => method === 'DELETE' && url === '/api/knowledge/previews/preview%2F2').length, successfulPreviewDeleteCount, '成功入库后不得清理已消费的预览')

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
const onlyChunk = document.querySelector('#chunk-preview .chunk-enabled')
onlyChunk.checked = false
document.querySelector('#index-continue').click()
assert.equal(document.querySelector('[data-upload-step="reviewing-index"]').hidden, false, '没有有效分块时应停留在索引预览')
assert.equal(document.activeElement, onlyChunk, '没有有效分块时应聚焦真实分块控件')
onlyChunk.checked = true

document.querySelector('[data-upload-nav="reviewing-metadata"]').click()
assert.equal(document.querySelector('#document-title').value, '参考合同', '返回已完成步骤应保留输入')
document.querySelector('#document-purpose').value = 'template-and-reference'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
assert.equal(document.querySelectorAll('#chunk-preview .chunk-card').length, 0, '用途变化必须失效旧分块预览')
document.querySelector('#template-family').value = '组合模板'
const changedPurposeRechunkCount = requests.filter(({ url }) => url.endsWith('/rechunk')).length
document.querySelector('#metadata-continue').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/rechunk')).length === changedPurposeRechunkCount + 1, '新用途必须重新生成分块')
await waitFor(() => document.querySelector('[data-upload-step="reviewing-index"]').hidden === false, '重新生成后应返回索引预览')
document.querySelector('[data-upload-nav="reviewing-metadata"]').click()

document.querySelector('#document-title').value = '保留的人工标题'
document.querySelector('#template-family').value = '保留的模板家族'
analyzeFails = true
document.querySelector('#analyze-metadata').click()
await waitFor(() => requests.at(-1)?.url.endsWith('/analyze'), '应发送失败场景的 AI 请求')
await waitFor(() => document.querySelector('#metadata-error').hidden === false, 'AI 失败应显示内联错误')
assert.equal(document.querySelector('#document-title').value, '保留的人工标题', 'AI 失败不得清空标题')
assert.equal(document.querySelector('#document-purpose').value, 'template-and-reference', 'AI 失败不得清空用途')
assert.equal(document.querySelector('#template-family').value, '保留的模板家族', 'AI 失败不得清空模板属性')

const cancelCleanupUrl = `/api/knowledge/previews/${encodeURIComponent(`preview/${previewSequence}`)}`
const cancelCleanupCount = requests.filter(({ url, method }) => method === 'DELETE' && url === cancelCleanupUrl).length
const cancelUpload = [...document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
cancelUpload.click()
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => requests.filter(({ url, method }) => method === 'DELETE' && url === cancelCleanupUrl).length === cancelCleanupCount + 1, '取消未保存上传应清理当前预览')
analyzeFails = false

document.querySelector('#page-action').click()
attachFile('文件A.docx')
const releaseOldPreview = holdNextResponse('preview')
const oldPreviewRequestCount = requests.filter(({ url }) => url === '/api/knowledge/preview').length
document.querySelector('#parse-document').click()
await waitFor(() => requests.filter(({ url }) => url === '/api/knowledge/preview').length === oldPreviewRequestCount + 1, '应发出延迟的文件 A 解析请求')
const stalePreviewUrl = `/api/knowledge/previews/${encodeURIComponent(`preview/${previewSequence}`)}`
document.querySelector('#document-id').value = 'old-document-id'
attachFile('文件B.docx')
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false, '解析中换文件应留在选择步骤')
releaseOldPreview()
await waitFor(() => requests.some(({ url, method }) => method === 'DELETE' && url === stalePreviewUrl), '文件变化后返回的旧预览必须立即删除')
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false, '旧解析响应不得推进新文件流程')
assert.equal(document.querySelector('#document-title').value, '文件B', '旧解析响应不得覆盖新文件表单')
assert.notEqual(document.querySelector('#document-id').value, 'old-document-id', '文件变化必须重建默认文档 ID')
assert.match(document.querySelector('#document-id').value, /^knowledge-\d+$/, '新默认文档 ID 应保持既有格式')

document.querySelector('#parse-document').click()
await waitFor(() => document.querySelector('[data-upload-step="reviewing-metadata"]').hidden === false, '文件 B 应能正常重新解析')
const releaseOldAnalysis = holdNextResponse('analyze')
const analyzeRequestCount = requests.filter(({ url }) => url.endsWith('/analyze')).length
document.querySelector('#analyze-metadata').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/analyze')).length === analyzeRequestCount + 1, '应发出延迟的文件 B 分析请求')
attachFile('文件C.docx')
releaseOldAnalysis()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false, '分析中换文件应留在选择步骤')
assert.equal(document.querySelector('#document-title').value, '文件C', '旧 AI 响应不得覆盖新文件标题')
assert.equal(document.querySelector('#document-purpose').value, '', '旧 AI 响应不得覆盖新文件用途')

document.querySelector('#parse-document').click()
await waitFor(() => document.querySelector('[data-upload-step="reviewing-metadata"]').hidden === false, '文件 C 应能正常重新解析')
document.querySelector('#document-title').value = '文件 C 参考资料'
document.querySelector('#document-purpose').value = 'reference-knowledge'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
const releaseOldChunks = holdNextResponse('rechunk')
const rechunkRequestCount = requests.filter(({ url }) => url.endsWith('/rechunk')).length
document.querySelector('#metadata-continue').click()
await waitFor(() => requests.filter(({ url }) => url.endsWith('/rechunk')).length === rechunkRequestCount + 1, '应发出延迟的文件 C 分块请求')
attachFile('文件D.docx')
releaseOldChunks()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false, '分块中换文件应留在选择步骤')
assert.equal(document.querySelectorAll('#chunk-preview .chunk-card').length, 0, '旧分块响应不得恢复失效 chunks')

const releaseClosedPreview = holdNextResponse('preview')
const closedPreviewRequestCount = requests.filter(({ url }) => url === '/api/knowledge/preview').length
document.querySelector('#parse-document').click()
await waitFor(() => requests.filter(({ url }) => url === '/api/knowledge/preview').length === closedPreviewRequestCount + 1, '应发出关闭场景的延迟解析请求')
const closedPreviewUrl = `/api/knowledge/previews/${encodeURIComponent(`preview/${previewSequence}`)}`
const closeDuringParse = [...document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
closeDuringParse.click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(document.querySelector('#editor-dialog').open, false, '非保存中的弹窗仍应允许取消')
releaseClosedPreview()
await waitFor(() => requests.some(({ url, method }) => method === 'DELETE' && url === closedPreviewUrl), '关闭后返回的新预览必须清理')
assert.equal(document.querySelector('#editor-dialog').open, false, '关闭后的旧解析响应不得重开或推进弹窗')

// Catches metadata confirmation capturing the old category while its creation POST is held.
document.querySelector('#page-action').click()
attachFile('单文件目录.docx')
document.querySelector('#parse-document').click()
await waitFor(() => !document.querySelector('[data-upload-step="reviewing-metadata"]').hidden, '单文件解析应完成')
document.querySelector('#document-purpose').value = 'generation-template'
document.querySelector('#document-purpose').dispatchEvent(new dom.window.Event('change', { bubbles: true }))
document.querySelector('#template-family').value = '单文件模板'
document.querySelector('#upload-category-create').click()
document.querySelector('#upload-category-name').value = '单文件新目录'
const releaseSingleCategory = holdNextResponse('category')
document.querySelector('#upload-category-save').click()
assert.equal(document.querySelector('#metadata-continue').disabled, true, '单文件创建目录期间必须禁止确认属性，避免丢失新目录')
document.querySelector('#metadata-continue').click()
assert.equal(document.querySelector('[data-upload-step="reviewing-metadata"]').hidden, false)
releaseSingleCategory()
await waitFor(() => document.querySelector('#document-category').value === 'single-created', '创建完成应选择新目录')
await waitFor(() => !document.querySelector('#metadata-continue').disabled, '创建完成应恢复继续按钮')
document.querySelector('#metadata-continue').click()
await waitFor(() => !document.querySelector('[data-upload-step="reviewing-index"]').hidden, '应继续索引审核')
document.querySelector('#index-continue').click()
document.querySelector('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(JSON.parse(requests.findLast(item => item.url.endsWith('/index')).body).categoryId, 'single-created', '最终提交必须使用新建目录，不得保存创建前快照')

// Catches late category completion mutating/focusing a disposed single-file owner.
document.querySelector('#page-action').click()
attachFile('关闭单文件目录.docx')
document.querySelector('#parse-document').click()
await waitFor(() => !document.querySelector('[data-upload-step="reviewing-metadata"]').hidden, '关闭场景应解析完成')
document.querySelector('#upload-category-create').click()
document.querySelector('#upload-category-name').value = '迟到目录'
const releaseClosedCategory = holdNextResponse('category')
document.querySelector('#upload-category-save').click()
const closedCategory = document.querySelector('#document-category')
const closedValue = closedCategory.value
let lateFocus = 0
closedCategory.focus = () => { lateFocus += 1 }
document.querySelector('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))
releaseClosedCategory()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(closedCategory.value, closedValue, '关闭后新目录不得改写旧选择')
assert.equal(lateFocus, 0, '关闭后新目录不得抢焦点')
console.log('knowledge-upload-check: ok')
