import { $, $$, escapeHtml } from './core/dom.js'
import { request } from './core/http.js'
import { replaceState } from './core/state.js'
import { renderAssistant } from './features/assistant.js'
import { renderDashboard } from './features/dashboard.js'
import { renderKnowledge } from './features/knowledge/index.js'
import { renderProcesses } from './features/processes/index.js'
import { renderSettings } from './features/settings.js'
import { renderSkills } from './features/skills/index.js'
import { setAction, setSecondaryAction } from './ui/feedback.js'
import { initializeIdentity } from './features/identity/auth.js'
import { renderAdmin } from './features/identity/admin.js'
import { renderProfile } from './features/identity/profile.js'
import { renderReviews } from './features/reviews/index.js'
import { identity, pageAllowed, applyPermissions, can } from './core/session.js'

const content = $('#content')
const pageTitle = $('#page-title')
const pageSubtitle = $('#page-subtitle')
const assistantHost = $('#assistant-host')

const pageInfo = {
  reviews: ['提交与审核', '保存草稿、提交审核，通过后发布到当前空间'],
  admin: ['系统管理', '管理部门账号、公司授权及权限组'],
  profile: ['个人中心', '管理个人信息、密码和登录设备'],
  dashboard: ['工作台', '流程规则、知识资产和 AI 服务概览'],
  processes: ['业务流程', '在流程步骤中定义输入、交付物和完成标准'],
  knowledge: ['知识库', '管理目录、文档模板、版本和向量索引'],
  skills: ['技能', '管理特殊任务的专业执行规则'],
  assistant: ['AI 助手', '上传当前任务文件，让 AI 判断流程并检索真实模板'],
  settings: ['系统设置', '配置助手规则、分块、召回和推荐策略'],
}

async function refresh() { replaceState(await request('/api/state')) }

const renderers = {
  reviews: renderReviews,
  admin: renderAdmin,
  profile: renderProfile,
  dashboard: renderDashboard,
  processes: () => renderProcesses(renderPage),
  knowledge: () => renderKnowledge(renderPage),
  skills: () => renderSkills(renderPage),
  assistant: renderAssistant,
  settings: () => renderSettings(renderPage),
}

export function renderPage() {
  if (!identity || identity.user.mustChangePassword) return
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
  if (!pageAllowed(page)) {
    content.hidden = false
    assistantHost.hidden = true
    content.innerHTML = '<div class="empty">当前账号没有此页面的访问权限，或此功能尚未启用。<p><a href="#dashboard">返回工作台</a></p></div>'
    return
  }
  content.hidden = page === 'assistant'
  assistantHost.hidden = page !== 'assistant'
  ;(renderers[page] || renderDashboard)()
  const createPermission = {processes:'processes', knowledge:'knowledge', skills:'skills'}[page]
  if (createPermission && !can(createPermission+'.create')) setAction('',null)
  applyPermissions(content)
  $('main').scrollTop = 0
}

export async function start() {
  if (!await initializeIdentity(start)) return
  content.innerHTML = '<div class="loading">正在连接部门数据库和知识服务…</div>'
  try { await refresh(); renderPage() } catch (error) { content.innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}</div>` }
}

if (!$('#navigation [data-page="admin"]')) $('#navigation').insertAdjacentHTML('beforeend','<a href="#admin" data-page="admin" aria-label="系统管理" title="系统管理"><i aria-hidden="true">⌘</i><span>系统管理</span></a><a href="#profile" data-page="profile" aria-label="个人中心" title="个人中心"><i aria-hidden="true">○</i><span>个人中心</span></a>')
window.addEventListener('hashchange', renderPage)
if (!$('#navigation [data-page="reviews"]')) $('#navigation').insertAdjacentHTML('beforeend','<a href="#reviews" data-page="reviews" aria-label="提交与审核" title="提交与审核"><i aria-hidden="true">✓</i><span>提交与审核</span></a>')
start()
