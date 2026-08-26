import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction } from '../../ui/dialog.js'
import { setAction, setSecondaryAction, toast } from '../../ui/feedback.js'
import { openProcessEditor } from './editor.js'

const content = $('#content')

async function refreshProcesses() {
  replaceState(await request('/api/state'))
  setSecondaryAction('', null)
  renderProcesses()
  $('main').scrollTop = 0
}

export function renderProcesses() {
  setAction('+ 新建流程', () => openProcessEditor(undefined, refreshProcesses))
  content.innerHTML = state.processes.length ? `<div class="process-list">${state.processes.map(process => `
    <article class="item-card process-card">
      <div class="item-head"><div><h3>${escapeHtml(process.name)}</h3><p>${escapeHtml(process.description)}</p></div><div class="actions"><button class="button small edit-process" data-id="${process.id}">编辑</button><button class="button small danger delete-process" data-id="${process.id}">删除</button></div></div>
      <div class="timeline">${process.steps.map((step, index) => `<div class="step-card"><small>第 ${index + 1} 步</small><b>${escapeHtml(step.name)}</b><p>${escapeHtml(step.objective)}</p><div class="meta"><span>${step.requiredInputs.length} 项输入</span><span>${step.requiredOutputs.length} 个交付物</span><span>${step.completionCriteria.length} 项标准</span></div></div>`).join('')}</div>
    </article>`).join('')}</div>` : '<div class="empty">还没有业务流程</div>'
  $$('.edit-process').forEach(button => button.onclick = () => openProcessEditor(state.processes.find(item => item.id === button.dataset.id), refreshProcesses))
  $$('.delete-process').forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个业务流程吗？', '流程及其全部步骤会被删除，此操作无法撤销。')) return
    try {
      await request(`/api/processes/${encodeURIComponent(button.dataset.id)}`, { method: 'DELETE' })
      await refreshProcesses()
      toast('已删除')
    } catch (error) { toast(error.message, true) }
  })
}
