import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from '../../../deepseek-harness/node_modules/jsdom/lib/api.js'

const root = new URL('../', import.meta.url)
const html = await readFile(new URL('index.html', root), 'utf8')
const app = await readFile(new URL('app.js', root), 'utf8')
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

const dom = new JSDOM(html, { url: 'http://127.0.0.1:3081/department#settings', runScripts: 'dangerously' })
const savedPayloads = []
dom.window.fetch = async (_url, options = {}) => {
  if (options.method === 'PUT') savedPayloads.push(JSON.parse(options.body))
  return { ok: true, json: async () => structuredClone(state) }
}
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true }
dom.window.HTMLDialogElement.prototype.close = function (returnValue = '') {
  this.returnValue = returnValue
  this.open = false
  this.dispatchEvent(new dom.window.Event('close'))
}
dom.window.requestAnimationFrame = callback => callback()
dom.window.eval(app)
await new Promise(resolve => setTimeout(resolve, 0))

const sections = [...dom.window.document.querySelectorAll('.settings-section')]
assert.deepEqual(sections.map(section => section.querySelector('h2')?.textContent), ['知识与检索', '助手行为', '模型与服务'], '设置项应按使用场景分组')
const rows = [...dom.window.document.querySelectorAll('.settings-row')]
assert.deepEqual(rows.map(row => row.querySelector('h3')?.textContent), ['默认分块设置', '检索与推荐', '文档用途', '部门助手规则', '模型与服务'])

const purposeButton = [...dom.window.document.querySelectorAll('.settings-row button')].find(button => button.textContent.includes('管理用途'))
assert.ok(purposeButton, '文档用途设置行应提供管理入口')
purposeButton.click()
assert.equal(dom.window.document.querySelector('#dialog-title')?.textContent, '管理文档用途')
await dom.window.closeAnimatedDialog(dom.window.document.querySelector('#editor-dialog'))

const assistantButton = [...dom.window.document.querySelectorAll('.settings-row button')].find(button => button.textContent.includes('配置规则'))
assistantButton.click()
assert.equal(dom.window.document.querySelector('#dialog-title')?.textContent, '部门助手规则')
dom.window.document.querySelector('#assistant-role').value = '更新后的部门助手'
dom.window.document.querySelector('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(savedPayloads[0].assistant.role, '更新后的部门助手')
assert.deepEqual(savedPayloads[0].chunking, state.settings.chunking, '单项保存不应覆盖其他设置')
assert.deepEqual(savedPayloads[0].retrieval, state.settings.retrieval, '单项保存不应覆盖其他设置')

assistantButton.click()
const cancelButton = [...dom.window.document.querySelectorAll('#editor-dialog .dialog-close')].find(button => button.textContent.includes('取消'))
cancelButton.click()
assert.equal(dom.window.document.querySelector('#editor-dialog').open, true, '关闭过渡期间弹窗应保持打开')
assert.equal(dom.window.document.querySelector('#editor-dialog').classList.contains('is-closing'), true, '关闭时应进入过渡状态')
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(dom.window.document.querySelector('#editor-dialog').open, false, '关闭过渡结束后弹窗应关闭')

console.log('settings-ui-check: ok')
