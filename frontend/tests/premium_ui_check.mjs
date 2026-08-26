import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createDom } from './helpers/dom.mjs'

const root = new URL('../', import.meta.url)
const premiumCss = await readFile(new URL('premium.css', root), 'utf8')
const state = {
  processes: [{
    id: 'process-1', name: '项目采购', description: '采购流程', steps: [{
      id: 'step-1', name: '需求确认', objective: '明确采购需求',
      requiredInputs: [], requiredOutputs: ['需求说明'], completionCriteria: ['范围明确'], instructions: '',
    }],
  }],
  categories: [], purposes: [],
  documents: [{ isGenerationTemplate: true, status: 'effective', indexed: true }],
  skills: [{
    id: 'contract-review', name: 'contract-review', description: '审查合同风险', instructions: '## 步骤', enabled: true, valid: true, error: '',
    resources: [{ path: 'scripts/review.py', kind: 'scripts', name: 'review.py', size: 128, updatedAt: '2026-08-24T00:00:00Z' }],
    resourceCounts: { scripts: 1, references: 0, assets: 0 }, updatedAt: '2026-08-24T00:00:00Z',
  }],
  settings: {
    assistant: { role: '部门助手', principles: ['先查真实资料'], defaultLanguage: 'zh-CN', draftByDefault: true, askWhenMissing: true },
    chunking: { mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80, parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30, cleanWhitespace: true, removeUrlsEmails: false },
    retrieval: { vectorRecall: 20, rerankTopN: 8, recommendCount: 3, scoreThreshold: null },
    embeddingModel: 'BAAI/bge-m3', rerankModel: 'BAAI/bge-reranker-v2-m3',
  },
  services: { database: true, docling: true, siliconflow: true, metadata: true, harness: true, harnessUrl: 'https://harness.example/department?embed=1' },
}

const requests = []
const dom = await createDom({ hash: 'dashboard', state, onRequest: (url, options) => {
  requests.push({ url, method: options.method || 'GET' })
} })
const [{ renderDashboard }, { renderAssistant }] = await Promise.all([
  import('../js/features/dashboard.js'),
  import('../js/features/assistant.js'),
])
assert.equal(typeof renderDashboard, 'function', '工作台 feature 应导出渲染函数')
assert.equal(typeof renderAssistant, 'function', 'AI 助手 feature 应导出渲染函数')
const premiumStyle = dom.window.document.createElement('style')
premiumStyle.textContent = premiumCss
dom.window.document.head.append(premiumStyle)
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
assert.match(dom.window.document.querySelector('.skill-resource-list')?.textContent || '', /review\.py/, '已有资源应显示在编辑器中')
dom.window.document.querySelector('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))
dom.window.document.querySelector('#page-action').click()
assert.ok(dom.window.document.querySelector('#skill-name').labels.length, '技能名称输入框应与可见标签关联')
assert.ok(dom.window.document.querySelector('#skill-description').labels.length, '技能说明输入框应与可见标签关联')
const scriptInput = dom.window.document.querySelector('#skill-resource-scripts')
Object.defineProperty(scriptInput, 'files', { value: [new dom.window.File(['print(1)'], 'helper.py', { type: 'text/x-python' })] })
scriptInput.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
assert.match(dom.window.document.querySelector('[data-resource-kind="scripts"]')?.textContent || '', /helper\.py/, '选择的脚本应作为待上传资源显示')
dom.window.document.querySelector('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))

dom.window.location.hash = '#processes'
dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'))
dom.window.document.querySelector('.delete-process').click()
await new Promise(resolve => setTimeout(resolve, 0))
assert.equal(dom.window.document.querySelector('#confirm-dialog')?.open, true, '删除操作应使用产品内确认弹窗')
assert.equal(requests.filter(request => request.method === 'DELETE').length, 0, '确认前不得发送删除请求')
dom.window.document.querySelector('#confirm-dialog button[value="cancel"]').click()
assert.equal(dom.window.document.querySelector('#confirm-dialog').classList.contains('is-closing'), true, '确认弹窗关闭时应进入统一过渡状态')
assert.equal(dom.window.document.querySelector('#confirm-dialog').open, true, '确认弹窗应在关闭过渡期间保持打开')
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(dom.window.document.querySelector('#confirm-dialog').open, false, '确认弹窗应在关闭过渡结束后关闭')

const timelineNodeRule = [...premiumStyle.sheet.cssRules].find(rule => rule.selectorText === '.process-card .step-card::before')
assert.equal(timelineNodeRule.style.left, '50%', '桌面端流程节点应位于步骤卡片的水平中心')
assert.equal(timelineNodeRule.style.transform, 'translateX(-50%)', '流程节点应按自身宽度精确居中')

console.log('premium-ui-check: ok')
