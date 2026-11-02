import { $, escapeHtml } from '../core/dom.js'
import { request } from '../core/http.js'
import { identity, spaceId, pageAllowed } from '../core/session.js'
import { setAction } from '../ui/feedback.js'

const assistantHost = $('#assistant-host')

export async function renderAssistant() {
  setAction('', null)
  if (!pageAllowed('assistant')) return
  const owner = identity.user.id, space = spaceId
  const key = owner + ':' + space
  if (assistantHost.dataset.owner === key && assistantHost.firstElementChild) return
  assistantHost.dataset.owner = key
  assistantHost.innerHTML = '<div class="loading" role="status">正在验证个人 AI 访问权限…</div>'
  const current = () => identity?.user.id === owner && spaceId === space && location.hash === '#assistant' && assistantHost.dataset.owner === key
  try {
    const entry = await request('/api/assistant/entry', {method:'POST'})
    if (!current()) { if (assistantHost.dataset.owner === key) assistantHost.dataset.owner = ''; return }
    const target = 'department-ai-' + crypto.randomUUID()
    assistantHost.innerHTML = `<div class="assistant-page"><div class="assistant-mode"><span class="badge">部门助手 / 通用编程</span><span class="muted">新会话中选择模式；设置 → 模型可配置个人服务。公司资料仍按当前权限提供。</span></div><iframe class="assistant-frame" name="${target}" title="个人 DeepSeek Harness AI 助手"></iframe></div>`
    const form = document.createElement('form')
    form.noValidate = true
    form.method = 'POST'
    form.action = entry.action
    form.target = target
    form.hidden = true
    const input = document.createElement('input')
    input.type = 'hidden'; input.name = 'ticket'; input.value = entry.ticket
    form.append(input); document.body.append(form)
    form.submit(); form.remove()
  } catch (error) {
    if (!current()) return
    assistantHost.innerHTML = `<div class="empty"><p role="alert">${escapeHtml(error.message)}</p><button class="button" id="assistant-retry">重新打开 AI 助手</button></div>`
    $('#assistant-retry').onclick = () => { assistantHost.dataset.owner = ''; renderAssistant() }
  }
}
