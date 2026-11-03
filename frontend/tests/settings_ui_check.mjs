import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const state = {
  processes: [], categories: [], documents: [], skills: [],
  purposes: [{ id: 'reference-knowledge', name: '参考知识', description: '正文检索', canGenerateTemplate: false, chunkBody: true, inheritChunking: true, chunkSettings: {}, documentCount: 0 }],
  settings: {
    assistant: { role: '部门助手', principles: ['先查真实资料'], defaultLanguage: 'zh-CN', draftByDefault: true, askWhenMissing: true },
    chunking: { mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80, parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30, cleanWhitespace: true, removeUrlsEmails: false },
    retrieval: { vectorRecall: 20, rerankTopN: 8, recommendCount: 3, scoreThreshold: null },
    embeddingModel: 'BAAI/bge-m3', rerankModel: 'BAAI/bge-reranker-v2-m3',
  },
  services: { database: true, docling: true, siliconflow: true, metadata: true, harness: true, harnessUrl: 'about:blank' },
}
state.purposes[0].chunkSettings = { ...state.settings.chunking }

const savedPayloads = []
const requests = []
const dom = await createDom({ hash: 'settings', state, onRequest: (url, options) => {
  requests.push({ url, method: options.method || 'GET' })
  if (options.method === 'PUT') savedPayloads.push(JSON.parse(options.body))
} })
await Promise.all([
  import('../js/ui/dialog.js'),
  import('../js/ui/form.js'),
  import('../js/ui/feedback.js'),
])

const sections = [...dom.window.document.querySelectorAll('.settings-section')]
assert.equal(dom.window.document.querySelector('#navigation [data-page="settings"]'), null)
assert.equal(dom.window.document.querySelector('#navigation [data-page="admin"]').getAttribute('aria-current'), 'page')
assert.equal(dom.window.document.querySelector('[data-admin-tab="settings"]').getAttribute('aria-selected'), 'true')
assert.equal(dom.window.document.querySelector('#admin-panel .settings-workspace') !== null, true)
assert.deepEqual(sections.map(section => section.querySelector('h2')?.textContent), ['知识与检索', '助手行为', '模型与服务'], '设置项应按使用场景分组')
const rows = [...dom.window.document.querySelectorAll('.settings-row')]
assert.deepEqual(rows.map(row => row.querySelector('h3')?.textContent), ['默认分块设置', '检索与推荐', '文档用途', '部门助手规则', '模型与服务'])

const purposeButton = [...dom.window.document.querySelectorAll('.settings-row button')].find(button => button.textContent.includes('管理用途'))
assert.ok(purposeButton, '文档用途设置行应提供管理入口')
purposeButton.click()
assert.equal(dom.window.document.querySelector('#dialog-title')?.textContent, '管理文档用途')
const purposeDialog = dom.window.document.querySelector('#editor-dialog')
const purposeForm = purposeDialog.querySelector('form')
let purposeSubmits = 0
const trackPurposeSubmit = event => { event.preventDefault(); purposeSubmits += 1 }
purposeForm.addEventListener('submit', trackPurposeSubmit)
const purposeRequestStart = requests.length
dom.window.document.querySelector('.edit-purpose').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(purposeSubmits, 0, '编辑用途不得默认提交外层 dialog 表单')
assert.equal(purposeDialog.open, true, '编辑用途弹窗应保持打开')
assert.equal(dom.window.document.querySelector('#dialog-title').textContent, '编辑文档用途')
assert.equal(dom.window.document.querySelector('#purpose-name').value, state.purposes[0].name)
await purposeDialog.requestClose()
purposeButton.click()
dom.window.document.querySelector('.delete-purpose').click()
assert.equal(purposeSubmits, 0, '删除用途不得默认提交外层 dialog 表单')
assert.equal(purposeDialog.open, true, '删除确认期间应保留用途管理弹窗')
assert.equal(dom.window.document.querySelector('#confirm-dialog').open, true)
dom.window.document.querySelector('#confirm-dialog button[value="cancel"]').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(purposeDialog.open, true, '取消删除后应保留用途管理弹窗')
assert.equal(dom.window.document.querySelector('#dialog-title').textContent, '管理文档用途')
assert.ok(requests.slice(purposeRequestStart).every(({ method }) => method === 'GET'), '编辑入口和取消删除不得写入用途')
purposeForm.removeEventListener('submit', trackPurposeSubmit)
const purposeCancelButton = [...dom.window.document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
purposeCancelButton.click()
await new Promise(resolve => setTimeout(resolve, 220))

const assistantButton = [...dom.window.document.querySelectorAll('.settings-row button')].find(button => button.textContent.includes('配置规则'))
assistantButton.click()
assert.equal(dom.window.document.querySelector('#dialog-title')?.textContent, '部门助手规则')
assert.equal(dom.window.document.querySelector('#editor-dialog').classList.contains('is-open'), true, '可见设置入口应以打开状态展示弹窗')
const assistantRole = dom.window.document.querySelector('#assistant-role')
assistantRole.value = ''
dom.window.document.querySelector('#dialog-save').click()
assert.equal(assistantRole.getAttribute('aria-invalid'), 'true', '无效必填字段应标记 aria-invalid')
assert.equal(dom.window.document.activeElement, assistantRole, '保存无效表单后应聚焦第一个错误字段')
assert.equal(assistantRole.closest('.field').querySelector('.field-error')?.textContent, '请填写角色定位')
assistantRole.value = '更新后的部门助手'
assistantRole.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
assert.equal(assistantRole.hasAttribute('aria-invalid'), false, '编辑字段时应清除无效状态')
const saveRequestStart = requests.length
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
await new Promise(resolve => setTimeout(resolve, 0))
assert.deepEqual(requests.slice(saveRequestStart, saveRequestStart + 2), [
  { url: '/api/settings', method: 'PUT' },
  { url: '/api/state', method: 'GET' },
], '单项设置保存后应完整刷新状态')
assert.equal(dom.window.document.body.dataset.page, 'dashboard', '设置异步刷新完成后应保留新路由状态')
assert.ok(dom.window.document.querySelector('#content .hero'), '设置异步刷新不得覆盖新路由内容')
assert.equal(savedPayloads[0].assistant.role, '更新后的部门助手')
assert.deepEqual(savedPayloads[0].chunking, state.settings.chunking, '单项保存不应覆盖其他设置')
assert.deepEqual(savedPayloads[0].retrieval, state.settings.retrieval, '单项保存不应覆盖其他设置')
const toast = dom.window.document.querySelector('#toast')
assert.equal(toast.getAttribute('role'), 'status', 'Toast 应复用既有状态区域')
assert.equal(toast.getAttribute('aria-live'), 'polite', 'Toast 状态区域应保持 polite 播报')
assert.equal(toast.textContent, '部门助手规则已保存')

dom.window.location.hash = '#settings'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
const refreshedAssistantButton = [...dom.window.document.querySelectorAll('.settings-row button')].find(button => button.textContent.includes('配置规则'))
refreshedAssistantButton.click()
const cancelButton = [...dom.window.document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
const scheduledTimers = []
const realSetTimeout = globalThis.setTimeout
try {
  globalThis.setTimeout = (callback, delay) => {
    scheduledTimers.push({ callback, delay })
    return scheduledTimers.length
  }
  cancelButton.click()
  assert.equal(dom.window.document.querySelector('#editor-dialog').open, true, '关闭过渡期间弹窗应保持打开')
  assert.equal(dom.window.document.querySelector('#editor-dialog').classList.contains('is-closing'), true, '关闭时应进入过渡状态')
  assert.equal(scheduledTimers[0]?.delay, 180, '弹窗关闭过渡应保持 180ms')
  scheduledTimers[0].callback()
  assert.equal(dom.window.document.querySelector('#editor-dialog').open, false, '关闭过渡结束后弹窗应关闭')
} finally {
  globalThis.setTimeout = realSetTimeout
}

const purposesModule = await import('../js/features/knowledge/purposes.js')
assert.equal(typeof purposesModule.openPurposeManager, 'function', '设置页应使用知识 feature 的用途管理入口')
const settingsModule = await import('../js/features/settings.js')
assert.deepEqual(Object.keys(settingsModule), ['renderSettings'], '设置 feature 应只导出页面入口')

console.log('settings-ui-check: ok')
