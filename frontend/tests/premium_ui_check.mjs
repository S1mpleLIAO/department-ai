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
// Business edit buttons now create review drafts; model those contracts explicitly.
const legacyFetch=globalThis.fetch
let reviewKind=''
const reviewResponse=body=>{
  reviewKind=body.kind
  const skill=state.skills[0]
  const data=body.kind==='processes'?state.processes[0]:{
    skill:{name:skill.name,description:skill.description,instructions:skill.instructions,enabled:skill.enabled},
    resources:[{path:skill.resources[0].path,contentBase64:'b2xk'}]
  }
  return {id:'revision-'+body.kind,kind:body.kind,targetId:body.targetId,revision:1,data}
}
dom.window.fetch=globalThis.fetch=async(url,options={})=>{
  if(String(url).startsWith('/api/reviews')){
    requests.push({url:String(url),method:options.method||'GET',body:options.body})
    const payload=String(url)==='/api/reviews/edits'?reviewResponse(JSON.parse(options.body)):
      String(url).includes('?')?{items:[],total:0,page:0}:{saved:true}
    return {ok:true,status:200,json:async()=>structuredClone(payload)}
  }
  return legacyFetch(url,options)
}
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
  'PostgreSQL / pgvector：可用', 'Docling：可用', 'Embedding / Rerank：已配置', 'AI 元数据分析：已配置',
], '工作台应区分服务可用性和模型配置状态')

dom.window.location.hash = '#assistant'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const assistantFrame = dom.window.document.querySelector('#assistant-host > .assistant-page > iframe.assistant-frame')
assert.equal(assistantFrame, null, '身份接入前不得加载共享 Harness')
dom.window.location.hash = '#dashboard'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
dom.window.location.hash = '#assistant'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.equal(dom.window.document.querySelector('.assistant-frame'), null, '路由重入仍不得加载共享 Harness')

dom.window.location.hash = '#settings'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.equal(dom.window.document.title, '系统设置 · 部门 AI', '路由变化应同步更新浏览器标题')

dom.window.location.hash = '#skills'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
assert.match(dom.window.document.querySelector('.skill-card .meta')?.textContent || '', /1 个脚本/, '技能卡片应显示资源数量')
dom.window.document.querySelector('.edit-skill').click()
await waitFor(()=>dom.window.document.querySelector('#skill-name'),'修改稿应打开技能表单')
assert.equal(dom.window.document.querySelectorAll('.skill-resource-card').length, 3, '编辑器应分别管理脚本、参考资料和素材')
assert.ok(dom.window.document.querySelector('#skill-resource-scripts').labels.length, '脚本上传控件应与可见标签关联')
assert.match(dom.window.document.querySelector('.skill-resource-list')?.textContent || '', /review 文件\.py/, '已有资源应显示在编辑器中')
assert.equal(dom.window.document.querySelector('.skill-resource-list a').getAttribute('href'), '/api/reviews/revision-skills/resources/scripts/review%20%E6%96%87%E4%BB%B6.py?space=zkxk', '资源下载路径应逐段编码并绑定空间')
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
dom.window.document.querySelector('#dialog-save').click()
await waitFor(()=>requests.slice(skillSaveStart).some(r=>r.url==='/api/reviews/revision-skills'),'技能修改应保存审核草稿')
await new Promise(resolve=>setTimeout(resolve,220))
const skillWrite=requests[skillSaveStart]
assert.equal(skillWrite.url,'/api/reviews/revision-skills')
assert.equal(skillWrite.method,'PUT')
assert.deepEqual(JSON.parse(skillWrite.body).data.resources,[{path:'scripts/helper 空.py',contentBase64:'QUJD'}])
assert.ok(!requests.slice(skillSaveStart).some(r=>r.url.startsWith('/api/skills')&&r.method!=='GET'),'不能提前修改正式技能及附件')

dom.window.location.hash = '#skills'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const skillDeleteStart = requests.length
dom.window.document.querySelector('.delete-skill').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '停用这个技能？', '技能移除采用停用')
assert.equal(dom.window.document.querySelector('#confirm-detail').textContent, '技能内容和附加资源将保留，停用后不再用于执行任务。', '应说明停用后果')
assert.equal(requests.length, skillDeleteStart, '技能删除确认前不得发送请求')
dom.window.document.querySelector('#confirm-dialog button[value="confirm"]').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.deepEqual(requests.slice(skillDeleteStart, skillDeleteStart + 2).map(({ url, method }) => ({ url, method })), [
  { url: '/api/skills/contract%2Freview%20%E4%B8%80', method: 'DELETE' },
  { url: '/api/state', method: 'GET' },
], '确认后应 DELETE 编码后的技能路径并完整刷新状态')
assert.equal(dom.window.document.querySelector('#toast').textContent, '技能已停用', '停用技能有成功反馈')

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
await waitFor(()=>dom.window.document.querySelector('#editor-dialog').open && dom.window.document.querySelector('#dialog-title').textContent==='编辑业务流程','应打开流程修改稿')
dom.window.document.querySelector('#process-name').value='更新流程'
const editRequestStart=requests.length
dom.window.document.querySelector('#dialog-save').click()
await waitFor(()=>requests.slice(editRequestStart).some(r=>r.url==='/api/reviews/revision-processes'),'应保存流程修改稿')
await new Promise(resolve=>setTimeout(resolve,220))
assert.equal(JSON.parse(requests[editRequestStart].body).data.name,'更新流程')
assert.ok(!requests.slice(editRequestStart).some(r=>r.url.startsWith('/api/processes')&&r.method==='PUT'),'流程修改不能提前覆盖正式版本')

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
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '归档这个业务流程？', '流程采用归档')
assert.equal(dom.window.document.querySelector('#confirm-detail').textContent, '归档后不再出现在当前流程列表，流程及步骤仍保留备查。', '应说明归档后果')
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
assert.equal(dom.window.document.querySelector('#toast').textContent, '流程已归档', '归档流程有成功反馈')

const documentDetail = {
  ...state.documents[0], originalPath: '/managed/test.txt', mimeType: 'text/plain', parsedText: '初始内容',
  outline: ['第一章'], chunks: [{ id: 'chunk-1', index: 0, parentIndex: null, sectionPath: '第一章', content: '初始内容', tokenCount: 4, enabled: true }],
}
const knowledgeFetch = async (url, options = {}) => {
  const request = { url: String(url), method: options.method || 'GET', body: options.body }
  requests.push(request)
  let payload = state
  if (request.url === '/api/documents/doc%2F%E4%B8%80%20%E5%8F%B7' && request.method === 'GET') payload = documentDetail
  else if (request.url==='/api/reviews/edits') payload={id:'revision-knowledge',kind:'knowledge',targetId:documentDetail.id,revision:1,
    data:{resourceId:documentDetail.id,parsedText:documentDetail.parsedText,metadata:{...documentDetail,id:'doc-valid-id',chunks:documentDetail.chunks}}}
  else if(request.url.startsWith('/api/reviews?'))payload={items:[],total:0,page:0}
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
await waitFor(()=>dom.window.document.querySelector('#document-title'),'应打开文档修改稿')
dom.window.document.querySelector('#document-title').value='更新知识'
dom.window.document.querySelector('#document-keywords').value='CPU、网络'
dom.window.document.querySelector('#document-summary').value='更新摘要'
const documentUpdateStart=requests.length
dom.window.document.querySelector('#dialog-save').click()
await waitFor(()=>requests.slice(documentUpdateStart).some(r=>r.url==='/api/reviews/revision-knowledge'),'文档修改应保存审核草稿')
await new Promise(resolve=>setTimeout(resolve,220))
assert.equal(requests[documentUpdateStart].method,'PUT')
assert.equal(JSON.parse(requests[documentUpdateStart].body).data.title,'更新知识')
assert.deepEqual(JSON.parse(requests[documentUpdateStart].body).data.keywords,['CPU','网络'])
assert.ok(!requests.slice(documentUpdateStart).some(r=>r.url.startsWith('/api/documents')&&r.method==='PUT'))
dom.window.location.hash='#knowledge'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))

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
assert.equal(dom.window.document.querySelector('#confirm-message').textContent, '废止这个文档？', '文档采用废止')
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
