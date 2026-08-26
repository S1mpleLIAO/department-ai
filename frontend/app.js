import { $, $$, escapeHtml } from './js/core/dom.js'
import { request } from './js/core/http.js'
import { replaceState } from './js/core/state.js'
import { renderAssistant } from './js/features/assistant.js'
import { renderDashboard } from './js/features/dashboard.js'
import { renderKnowledge } from './js/features/knowledge/index.js'
import { renderProcesses } from './js/features/processes/index.js'
import { renderSettings } from './js/features/settings.js'
import { renderSkills } from './js/features/skills/index.js'
import { setAction, setSecondaryAction } from './js/ui/feedback.js'

const content = $('#content')
const pageTitle = $('#page-title')
const pageSubtitle = $('#page-subtitle')
const assistantHost = $('#assistant-host')

const pageInfo = {
  dashboard: ['工作台', '流程规则、知识资产和 AI 服务概览'],
  processes: ['业务流程', '在流程步骤中定义输入、交付物和完成标准'],
  knowledge: ['知识库', '管理目录、文档模板、版本和向量索引'],
  skills: ['技能', '管理特殊任务的专业执行规则'],
  assistant: ['AI 助手', '上传当前任务文件，让 AI 判断流程并检索真实模板'],
  settings: ['系统设置', '配置助手规则、分块、召回和推荐策略'],
}

async function refresh() { replaceState(await request('/api/state')) }

function renderPage() {
  let page = location.hash.slice(1) || 'dashboard'
  if (page === 'purposes') { page = 'knowledge'; history.replaceState(null, '', '#knowledge') }
  const [title, subtitle] = pageInfo[page] || pageInfo.dashboard
  document.title = `${title} · 部门 AI`
  document.body.dataset.page = page
  pageTitle.textContent = title
  pageSubtitle.textContent = subtitle
  $$('#navigation a').forEach(link => {
    const active = link.dataset.page === page
    link.classList.toggle('active', active)
    if (active) link.setAttribute('aria-current', 'page')
    else link.removeAttribute('aria-current')
  })
  setAction('', null)
  setSecondaryAction('', null)
  content.hidden = page === 'assistant'
  assistantHost.hidden = page !== 'assistant'
  const renderers = {
    dashboard: renderDashboard,
    processes: () => renderProcesses(renderPage),
    knowledge: () => renderKnowledge(renderPage),
    skills: () => renderSkills(renderPage),
    assistant: renderAssistant,
    settings: () => renderSettings(renderPage),
  }
  ;(renderers[page] || renderDashboard)()
  $('main').scrollTop = 0
}

async function start() {
  content.innerHTML = '<div class="loading">正在连接部门数据库和知识服务…</div>'
  try { await refresh(); renderPage() } catch (error) { content.innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}</div>` }
}

window.addEventListener('hashchange', renderPage)
start()
