import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createDom } from './helpers/dom.mjs'

const root = new URL('../', import.meta.url)
const featuresCss = await readFile(new URL('css/features.css', root), 'utf8')
const state = {
  processes: [{
    id: 'process/一 号', name: '项目采购', description: '采购流程', steps: [{
      id: 'step-1', name: '需求确认', objective: '明确采购需求',
      requiredInputs: [], requiredOutputs: ['需求说明'], completionCriteria: ['范围明确'], instructions: '',
    }],
  }],
  categories: [{ id: 'cat/一 号', name: '测试目录', parentId: null }],
  purposes: [{
    id: 'reference-knowledge', name: '参考知识', description: '正文检索', canGenerateTemplate: false,
    chunkBody: true, inheritChunking: true, chunkSettings: {}, documentCount: 1,
  }],
  documents: [{
    id: 'doc/一 号', title: '测试知识', originalName: '测试知识.txt', categoryId: 'cat/一 号',
    purposeId: 'reference-knowledge', purposeName: '参考知识', documentType: '说明', status: 'effective',
    keywords: ['CPU'], isGenerationTemplate: true, isReferenceKnowledge: true, indexed: true,
    documentIndexed: true, chunkIndexed: true, chunkCount: 1, templateFamily: '测试模板', templateVariant: '',
    version: 'V1.0', applicableScenario: '测试', summary: '测试摘要', updatedAt: '2026-08-24T00:00:00Z',
  }],
  skills: [{
    id: 'contract/review 一', name: 'contract-review', description: '审查合同风险', instructions: '## 步骤', enabled: true, valid: true, error: '',
    resources: [{ path: 'scripts/review 文件.py', kind: 'scripts', name: 'review 文件.py', size: 128, updatedAt: '2026-08-24T00:00:00Z' }],
    resourceCounts: { scripts: 1, references: 0, assets: 0 }, updatedAt: '2026-08-24T00:00:00Z',
  }],
  skill: { id: 'contract/review 一' },
  settings: {
    assistant: { role: '部门助手', principles: ['先查真实资料'], defaultLanguage: 'zh-CN', draftByDefault: true, askWhenMissing: true },
    chunking: { mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80, parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30, cleanWhitespace: true, removeUrlsEmails: false },
    retrieval: { vectorRecall: 20, rerankTopN: 8, recommendCount: 3, scoreThreshold: null },
    embeddingModel: 'BAAI/bge-m3', rerankModel: 'BAAI/bge-reranker-v2-m3',
  },
  services: { database: true, docling: true, siliconflow: true, metadata: true, harness: true, harnessUrl: 'https://harness.example/department?embed=1' },
}

const requests = []
async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 0))
  }
  assert.fail(message)
}

const dom = await createDom({ hash: 'dashboard', state, onRequest: (url, options) => {
  requests.push({ url, method: options.method || 'GET', body: options.body })
} })
const [{ renderDashboard }, { renderAssistant }] = await Promise.all([
  import('../js/features/dashboard.js'),
  import('../js/features/assistant.js'),
])
assert.equal(typeof renderDashboard, 'function', '工作台 feature 应导出渲染函数')
assert.equal(typeof renderAssistant, 'function', 'AI 助手 feature 应导出渲染函数')
const featuresStyle = dom.window.document.createElement('style')
featuresStyle.textContent = featuresCss
dom.window.document.head.append(featuresStyle)
dom.window.confirm = () => false

assert.match(dom.window.document.querySelector('.hero')?.textContent || '', /部门任务入口/, '工作台应保留任务入口内容')
assert.deepEqual([...dom.window.document.querySelectorAll('.stat-card')].map(card => card.textContent.trim()), [
  '业务流程1', '流程步骤1', '有效生成模板1', '已建立索引文档1',
], '工作台应展示现有流程、步骤、模板和索引统计')
assert.deepEqual([...dom.window.document.querySelectorAll('.service-strip .service-badge')].map(badge => badge.textContent), [
  'PostgreSQL / pgvector', 'Docling', 'Embedding / Rerank 已配置', 'DeepSeek Harness',
], '工作台应保留现有服务状态内容')

dom.window.location.hash = '#assistant'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const assistantFrame = dom.window.document.querySelector('#assistant-host > .assistant-page > iframe.assistant-frame')
assert.equal(assistantFrame?.getAttribute('src'), state.services.harnessUrl, 'AI 助手应使用状态中的 Harness URL')
assert.equal(assistantFrame?.getAttribute('title'), 'DeepSeek Harness AI 助手', 'Harness iframe 应保留可访问标题')
dom.window.location.hash = '#dashboard'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
dom.window.location.hash = '#assistant'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.equal(dom.window.document.querySelector('.assistant-frame'), assistantFrame, '返回 AI 助手时应复用现有 Harness iframe')

dom.window.location.hash = '#settings'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.equal(dom.window.document.title, '系统设置 · 部门 AI', '路由变化应同步更新浏览器标题')

dom.window.location.hash = '#skills'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.match(dom.window.document.querySelector('.skill-card .meta')?.textContent || '', /1 个脚本/, '技能卡片应显示资源数量')
dom.window.document.querySelector('.edit-skill').click()
assert.equal(dom.window.document.querySelectorAll('.skill-resource-card').length, 3, '编辑器应分别管理脚本、参考资料和素材')
assert.ok(dom.window.document.querySelector('#skill-resource-scripts').labels.length, '脚本上传控件应与可见标签关联')
assert.match(dom.window.document.querySelector('.skill-resource-list')?.textContent || '', /review 文件\.py/, '已有资源应显示在编辑器中')
assert.equal(dom.window.document.querySelector('.skill-resource-list a').getAttribute('href'), '/api/skills/contract%2Freview%20%E4%B8%80/resources/scripts/review%20%E6%96%87%E4%BB%B6.py', '资源下载路径应逐段编码')
assert.ok(dom.window.document.querySelector('#skill-name').labels.length, '技能名称输入框应与可见标签关联')
assert.ok(dom.window.document.querySelector('#skill-description').labels.length, '技能说明输入框应与可见标签关联')
dom.window.document.querySelector('.resource-remove').click()
const scriptInput = dom.window.document.querySelector('#skill-resource-scripts')
const pendingFile = new dom.window.File(['ABC'], 'helper 空.py', { type: 'text/x-python' })
Object.defineProperty(pendingFile, 'arrayBuffer', { value: async () => Uint8Array.from([65, 66, 67]).buffer })
Object.defineProperty(scriptInput, 'files', { value: [pendingFile] })
scriptInput.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
assert.match(dom.window.document.querySelector('[data-resource-kind="scripts"]')?.textContent || '', /helper 空\.py/, '选择的脚本应作为待上传资源显示')
const skillSaveStart = requests.length
const skillRealFetch = globalThis.fetch
let releaseSkillStateRefresh
let markSkillStateRefreshStarted
const skillStateRefreshStarted = new Promise(resolve => { markSkillStateRefreshStarted = resolve })
try {
  const delayedFetch = async (url, options = {}) => {
    if (String(url) === '/api/state' && (options.method || 'GET') === 'GET') {
      markSkillStateRefreshStarted()
      await new Promise(resolve => { releaseSkillStateRefresh = resolve })
    }
    return skillRealFetch(url, options)
  }
  dom.window.fetch = globalThis.fetch = delayedFetch
  dom.window.document.querySelector('#dialog-save').click()
  await skillStateRefreshStarted
  dom.window.location.hash = '#dashboard'
  dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
  const refreshedContent = new Promise(resolve => {
    const observer = new dom.window.MutationObserver(() => { observer.disconnect(); resolve() })
    observer.observe(dom.window.document.querySelector('#content'), { childList: true })
  })
  releaseSkillStateRefresh()
  await refreshedContent
} finally {
  dom.window.fetch = globalThis.fetch = skillRealFetch
}
await new Promise(resolve => setTimeout(resolve, 0))
assert.deepEqual(requests.slice(skillSaveStart, skillSaveStart + 4).map(({ url, method }) => ({ url, method })), [
  { url: '/api/skills/contract%2Freview%20%E4%B8%80', method: 'PUT' },
  { url: '/api/skills/contract%2Freview%20%E4%B8%80/resources/scripts/review%20%E6%96%87%E4%BB%B6.py', method: 'DELETE' },
  { url: '/api/skills/contract%2Freview%20%E4%B8%80/resources/scripts/helper%20%E7%A9%BA.py', method: 'PUT' },
  { url: '/api/state', method: 'GET' },
], '技能保存应依次保存主体、删除旧资源、上传新资源并刷新状态')
assert.deepEqual(JSON.parse(requests[skillSaveStart + 2].body), { contentBase64: 'QUJD' }, '资源上传应发送准确 Base64 内容')
assert.equal(dom.window.document.body.dataset.page, 'dashboard', '技能异步刷新完成后应保留新路由状态')
assert.ok(dom.window.document.querySelector('#content .hero'), '技能异步刷新不得覆盖新路由内容')

dom.window.location.hash = '#skills'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const skillDeleteStart = requests.length
dom.window.document.querySelector('.delete-skill').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '确定删除这个技能吗？', '应保留技能删除确认文案')
assert.equal(dom.window.document.querySelector('#confirm-detail').textContent, '对应的 SKILL.md 文件会一并删除。', '应保留技能删除确认详情')
assert.equal(requests.length, skillDeleteStart, '技能删除确认前不得发送请求')
dom.window.document.querySelector('#confirm-dialog button[value="confirm"]').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.deepEqual(requests.slice(skillDeleteStart, skillDeleteStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/skills/contract%2Freview%20%E4%B8%80', method: 'DELETE' },
  { url: '/api/state', method: 'GET' },
], '确认后应 DELETE 编码后的技能路径并完整刷新状态')
assert.equal(dom.window.document.querySelector('#toast').textContent, '技能已删除', '删除技能应保留成功 Toast')

dom.window.location.hash = '#processes'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
dom.window.document.querySelector('#page-action').click()
dom.window.document.querySelector('#process-name').value = '新建流程'
dom.window.document.querySelector('.step-editor [data-key="name"]').value = '新建步骤'
dom.window.document.querySelector('.step-editor [data-key="objective"]').value = '完成新建流程'
dom.window.document.querySelector('main').scrollTop = 64
const createRequestStart = requests.length
dom.window.document.querySelector('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.deepEqual(requests.slice(createRequestStart, createRequestStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/processes', method: 'POST' },
  { url: '/api/state', method: 'GET' },
], '新建流程应 POST 后完整刷新状态')
assert.equal(JSON.parse(requests[createRequestStart].body).name, '新建流程', '新建流程应发送编辑器数据')
assert.equal(dom.window.document.querySelector('main').scrollTop, 0, '流程保存后应保留页面重绘的滚动重置')
assert.equal(dom.window.document.querySelector('#toast').textContent, '已保存', '新建流程应保留成功 Toast')

dom.window.document.querySelector('.edit-process').click()
dom.window.document.querySelector('#process-name').value = '更新流程'
const editRequestStart = requests.length
const realFetch = globalThis.fetch
let releaseStateRefresh
let markStateRefreshStarted
const stateRefreshStarted = new Promise(resolve => { markStateRefreshStarted = resolve })
try {
  const delayedFetch = async (url, options = {}) => {
    if (String(url) === '/api/state' && (options.method || 'GET') === 'GET') {
      markStateRefreshStarted()
      await new Promise(resolve => { releaseStateRefresh = resolve })
    }
    return realFetch(url, options)
  }
  dom.window.fetch = globalThis.fetch = delayedFetch
  dom.window.document.querySelector('#dialog-save').click()
  await stateRefreshStarted

  dom.window.location.hash = '#dashboard'
  dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
  const refreshedContent = new Promise(resolve => {
    const observer = new dom.window.MutationObserver(() => { observer.disconnect(); resolve() })
    observer.observe(dom.window.document.querySelector('#content'), { childList: true })
  })
  releaseStateRefresh()
  await refreshedContent
} finally {
  dom.window.fetch = globalThis.fetch = realFetch
}
assert.deepEqual(requests.slice(editRequestStart, editRequestStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/processes/process%2F%E4%B8%80%20%E5%8F%B7', method: 'PUT' },
  { url: '/api/state', method: 'GET' },
], '编辑流程应 PUT 到编码后路径并完整刷新状态')
assert.equal(JSON.parse(requests[editRequestStart].body).name, '更新流程', '编辑流程应发送编辑器数据')
assert.equal(dom.window.document.body.dataset.page, 'dashboard', '异步刷新完成后应保留新路由的 body 状态')
assert.equal(dom.window.document.title, '工作台 · 部门 AI', '异步刷新完成后应保留新路由标题')
assert.equal(dom.window.document.querySelector('#navigation a.active')?.dataset.page, 'dashboard', '异步刷新完成后应保留新路由导航')
assert.ok(dom.window.document.querySelector('#content .hero'), '异步刷新完成后应保留新路由内容')
assert.equal(dom.window.document.querySelector('#content .process-card'), null, '异步刷新不得用流程 DOM 覆盖新路由')

dom.window.location.hash = '#processes'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))

dom.window.document.querySelector('#page-action').click()
const processCancelButton = [...dom.window.document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
const processCancelTimers = []
const processRealSetTimeout = globalThis.setTimeout
try {
  globalThis.setTimeout = (callback, delay) => {
    processCancelTimers.push({ callback, delay })
    return processCancelTimers.length
  }
  processCancelButton.click()
  assert.equal(dom.window.document.querySelector('#editor-dialog').open, true, '流程编辑器关闭过渡期间应保持打开')
  assert.equal(dom.window.document.querySelector('#editor-dialog').classList.contains('is-closing'), true, '流程编辑器取消时应进入关闭过渡')
  assert.equal(processCancelTimers[0]?.delay, 180, '流程编辑器取消应保持 180ms 过渡')
  processCancelTimers[0].callback()
  assert.equal(dom.window.document.querySelector('#editor-dialog').open, false, '流程编辑器应在过渡后关闭')
} finally {
  globalThis.setTimeout = processRealSetTimeout
}

const deleteRequestStart = requests.length
dom.window.document.querySelector('.delete-process').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(dom.window.document.querySelector('#confirm-dialog')?.open, true, '删除操作应使用产品内确认弹窗')
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '确定删除这个业务流程吗？', '应保留流程删除确认文案')
assert.equal(dom.window.document.querySelector('#confirm-detail').textContent, '流程及其全部步骤会被删除，此操作无法撤销。', '应保留流程删除确认详情')
assert.equal(requests.length, deleteRequestStart, '确认前不得发送任何请求')
dom.window.document.querySelector('#confirm-dialog button[value="cancel"]').click()
assert.equal(dom.window.document.querySelector('#confirm-dialog').classList.contains('is-closing'), true, '确认弹窗关闭时应进入统一过渡状态')
assert.equal(dom.window.document.querySelector('#confirm-dialog').open, true, '确认弹窗应在关闭过渡期间保持打开')
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(dom.window.document.querySelector('#confirm-dialog').open, false, '确认弹窗应在关闭过渡结束后关闭')

dom.window.document.querySelector('.delete-process').click()
await new Promise(resolve => setTimeout(resolve, 0))
const confirmedDeleteStart = requests.length
dom.window.document.querySelector('#confirm-dialog button[value="confirm"]').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.deepEqual(requests.slice(confirmedDeleteStart, confirmedDeleteStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/processes/process%2F%E4%B8%80%20%E5%8F%B7', method: 'DELETE' },
  { url: '/api/state', method: 'GET' },
], '确认后应 DELETE 编码后路径并完整刷新状态')
assert.equal(dom.window.location.hash, '#processes', '流程保存与删除后应保留当前路由')
assert.equal(dom.window.document.querySelector('#toast').textContent, '已删除', '删除流程应保留成功 Toast')

const documentDetail = {
  ...state.documents[0], originalPath: '/managed/test.txt', mimeType: 'text/plain', parsedText: '初始内容',
  outline: ['第一章'], chunks: [{ id: 'chunk-1', index: 0, parentIndex: null, sectionPath: '第一章', content: '初始内容', tokenCount: 4, enabled: true }],
}
const knowledgeFetch = async (url, options = {}) => {
  const request = { url: String(url), method: options.method || 'GET', body: options.body }
  requests.push(request)
  let payload = state
  if (request.url === '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7' && request.method === 'GET') payload = documentDetail
  else if (request.method === 'DELETE') payload = { deleted: true }
  else if (request.method !== 'GET') payload = { saved: true }
  return { ok: true, json: async () => structuredClone(payload) }
}
dom.window.fetch = globalThis.fetch = knowledgeFetch

dom.window.location.hash = '#knowledge'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.equal(dom.window.document.querySelector('.document-row')?.dataset.id, 'doc/一 号', '知识页应渲染可见文档行')

dom.window.location.hash = '#knowledge'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const documentOpenStart = requests.length
dom.window.document.querySelector('.view-document').click()
await waitFor(() => dom.window.document.querySelector('#dialog-title')?.textContent === '测试知识', '应打开文档详情')
assert.deepEqual(requests[documentOpenStart], { url: '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7', method: 'GET', body: undefined }, '文档详情应 GET 编码后路径')
dom.window.document.querySelector('#edit-document').click()
await new Promise(resolve => setTimeout(resolve, 220))
dom.window.document.querySelector('#edit-document-title').value = '更新知识'
dom.window.document.querySelector('#edit-document-keywords').value = 'CPU、网络'
dom.window.document.querySelector('#edit-document-summary').value = '更新摘要'
const documentUpdateStart = requests.length
dom.window.document.querySelector('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => requests.length >= documentUpdateStart + 2, '文档保存后应刷新状态')
assert.deepEqual(requests.slice(documentUpdateStart, documentUpdateStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7', method: 'PUT' },
  { url: '/api/state', method: 'GET' },
], '文档编辑应 PUT 编码后路径并刷新状态')
assert.deepEqual(JSON.parse(requests[documentUpdateStart].body), {
  title: '更新知识', categoryId: 'cat/一 号', status: 'effective', documentType: '说明', keywords: ['CPU', '网络'],
  outline: ['第一章'], templateFamily: '测试模板', templateVariant: '', version: 'V1.0', applicableScenario: '测试', summary: '更新摘要',
}, '文档更新 body 应删除 id 并保留精确元数据字段')

dom.window.document.querySelector('.view-document').click()
await waitFor(() => dom.window.document.querySelector('#reindex-document'), '应重新打开文档详情')
const reindexStart = requests.length
dom.window.document.querySelector('#reindex-document').click()
await new Promise(resolve => setTimeout(resolve, 220))
await waitFor(() => requests.length >= reindexStart + 2, '重建索引后应刷新状态')
assert.deepEqual(requests.slice(reindexStart, reindexStart + 2).map(({ url, method, body }) => ({ url, method, body })), [
  { url: '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7/reindex', method: 'POST', body: undefined },
  { url: '/api/state', method: 'GET', body: undefined },
], '文档重建应 POST 编码后路径且不发送 body')

dom.window.document.querySelector('.view-document').click()
await waitFor(() => dom.window.document.querySelector('#delete-document'), '删除前应打开文档详情')
const documentDeleteStart = requests.length
dom.window.document.querySelector('#delete-document').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(requests.length, documentDeleteStart, '文档删除确认前不得发送请求')
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '确定删除这个文档吗？', '应保留文档删除确认文案')
dom.window.document.querySelector('#confirm-dialog button[value="confirm"]').click()
await new Promise(resolve => setTimeout(resolve, 420))
assert.deepEqual(requests.slice(documentDeleteStart, documentDeleteStart + 2).map(({ url, method, body }) => ({ url, method, body })), [
  { url: '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7', method: 'DELETE', body: undefined },
  { url: '/api/state', method: 'GET', body: undefined },
], '确认后应 DELETE 编码后文档路径并刷新状态')

const knowledgeModules = await Promise.all([
  import('../js/features/knowledge/index.js'),
  import('../js/features/knowledge/categories.js'),
  import('../js/features/knowledge/purposes.js'),
  import('../js/features/knowledge/documents.js'),
  import('../js/features/knowledge/upload.js'),
])
assert.equal(typeof knowledgeModules[0].renderKnowledge, 'function', '知识 feature 应导出页面渲染入口')

const { replaceState } = await import('../js/core/state.js')
replaceState({ ...state, documents: [...state.documents, { ...state.documents[0], id: 'unclassified', categoryId: null }] })
knowledgeModules[0].renderKnowledge(() => {})
dom.window.document.querySelector('.category-select').click()
const unclassifiedView = dom.window.document.querySelector('[data-knowledge-view="unclassified"]')
assert.ok(unclassifiedView, '知识库应提供待整理系统视图')
unclassifiedView.click()
assert.deepEqual([...dom.window.document.querySelectorAll('.document-row')].map(row => row.dataset.id), ['unclassified'], '待整理仅显示空目录文档')
dom.window.document.querySelector('#page-action').click()
assert.equal(dom.window.document.querySelector('#document-category').value, '', '待整理上传应以空目录开始')
dom.window.document.querySelector('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))

const timelineNodeRule = [...featuresStyle.sheet.cssRules].find(rule => rule.selectorText === '.process-card .step-card::before')
assert.equal(timelineNodeRule.style.left, '50%', '桌面端流程节点应位于步骤卡片的水平中心')
assert.equal(timelineNodeRule.style.transform, 'translateX(-50%)', '流程节点应按自身宽度精确居中')

const [{ renderProcesses }, { openProcessEditor }] = await Promise.all([
  import('../js/features/processes/index.js'),
  import('../js/features/processes/editor.js'),
])
assert.equal(typeof renderProcesses, 'function', '流程 feature 应导出页面渲染函数')
assert.equal(typeof openProcessEditor, 'function', '流程 editor 应导出编辑器函数')
const [skillsModule, skillEditorModule] = await Promise.all([
  import('../js/features/skills/index.js'),
  import('../js/features/skills/editor.js'),
])
assert.deepEqual(Object.keys(skillsModule), ['renderSkills'], '技能 feature 只应导出页面渲染函数')
assert.deepEqual(Object.keys(skillEditorModule), ['openSkillEditor'], '技能 editor 只应导出编辑器函数')

console.log('premium-ui-check: ok')
