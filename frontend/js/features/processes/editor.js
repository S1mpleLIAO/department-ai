import { $, $$, escapeHtml } from '../../core/dom.js'
import { lineValues, lines } from '../../core/format.js'
import { request } from '../../core/http.js'
import { requiresReview } from '../../core/session.js'
import { dialogContent, openDialog } from '../../ui/dialog.js'

function stepEditor(step = {}, index = 0) {
  return `<div class="step-editor" draggable="true" data-step-id="${escapeHtml(step.id || '')}">
    <div class="step-editor-head"><b>步骤 ${index + 1}</b><div class="actions"><button type="button" class="button small step-up">上移</button><button type="button" class="button small step-down">下移</button><button type="button" class="button small danger step-remove">删除</button></div></div>
    <div class="form-grid">
      <div class="field full"><label>步骤名称</label><input data-key="name" value="${escapeHtml(step.name || '')}" placeholder="采购需求确认" required></div>
      <div class="field full"><label>步骤目标</label><textarea data-key="objective" required>${escapeHtml(step.objective || '')}</textarea></div>
      <div class="field"><label>必须具备的输入</label><textarea data-key="requiredInputs" placeholder="每行一项">${escapeHtml(lines(step.requiredInputs))}</textarea></div>
      <div class="field"><label>必须形成的交付物</label><textarea data-key="requiredOutputs" placeholder="每行一项">${escapeHtml(lines(step.requiredOutputs))}</textarea></div>
      <div class="field"><label>完成标准</label><textarea data-key="completionCriteria" placeholder="每行一项">${escapeHtml(lines(step.completionCriteria))}</textarea></div>
      <div class="field"><label>执行说明</label><textarea data-key="instructions" placeholder="AI 在这一步需要遵循的具体规则">${escapeHtml(step.instructions || '')}</textarea></div>
    </div></div>`
}

function renumberSteps() { $$('.step-editor', dialogContent).forEach((node, index) => $('.step-editor-head b', node).textContent = `步骤 ${index + 1}`) }

export function openProcessEditor(process, afterSave, {draft=null}={}) {
  const review = Boolean(draft) || (!process && requiresReview('processes'))
  const draftId = draft?.id || crypto.randomUUID()
  const current = process || { id: '', name: '', description: '', steps: [{}] }
  openDialog(process ? '编辑业务流程' : '新建业务流程', draft?.targetId?'正在编辑修改稿；提交审核并发布前，正式流程保持不变。':'任务要求直接定义在流程步骤中，不再单独维护任务模板', `
    <div class="form-grid process-basics">
      <div class="field full"><label>流程名称</label><input id="process-name" value="${escapeHtml(current.name)}" placeholder="例如：项目采购" required></div>
      <div class="field full"><label>流程说明</label><textarea id="process-description" placeholder="说明这个流程适用于什么业务场景">${escapeHtml(current.description)}</textarea></div>
    </div>
    <div class="section-heading"><div><h2>流程步骤</h2><p>拖动卡片或使用按钮调整顺序</p></div><button type="button" id="add-step" class="button small">+ 添加步骤</button></div>
    <div class="steps-editor">${current.steps.map(stepEditor).join('')}</div>`, async () => {
      const steps = $$('.step-editor', dialogContent).map(node => ({
        id: node.dataset.stepId || undefined,
        name: $('[data-key="name"]', node).value.trim(),
        objective: $('[data-key="objective"]', node).value.trim(),
        requiredInputs: lineValues($('[data-key="requiredInputs"]', node).value),
        requiredOutputs: lineValues($('[data-key="requiredOutputs"]', node).value),
        completionCriteria: lineValues($('[data-key="completionCriteria"]', node).value),
        instructions: $('[data-key="instructions"]', node).value.trim(),
      }))
      const method = process ? 'PUT' : 'POST'
      const path = process ? `/api/processes/${encodeURIComponent(process.id)}` : '/api/processes'
      const data={ id: process?.id, name: $('#process-name').value.trim(), description: $('#process-description').value.trim(), steps }
      if(review) await request(draft ? '/api/reviews/'+draft.id : '/api/reviews', {method:draft?'PUT':'POST',body:draft?{revision:draft.revision,data}:{id:draftId,kind:'processes',data}})
      else await request(path, { method, body:data })
    }, { wide: true, guardChanges:review, saveLabel:review?'保存草稿':'保存',successMessage:review?'草稿已保存，请在提交与审核中提交':'已保存',
      afterSave:async()=>{await afterSave?.(); if(review&&!draft)location.hash='#reviews'} })
  $('#add-step').onclick = () => { $('.steps-editor').insertAdjacentHTML('beforeend', stepEditor({}, $$('.step-editor').length)); renumberSteps(); dialogContent.dispatchEvent(new Event('input',{bubbles:true})) }
  dialogContent.onclick = event => {
    const card = event.target.closest('.step-editor')
    if (!card) return
    if(event.target.closest('.step-remove,.step-up,.step-down'))dialogContent.dispatchEvent(new Event('input',{bubbles:true}))
    if (event.target.closest('.step-remove')) card.remove()
    if (event.target.closest('.step-up') && card.previousElementSibling) card.parentElement.insertBefore(card, card.previousElementSibling)
    if (event.target.closest('.step-down') && card.nextElementSibling) card.parentElement.insertBefore(card.nextElementSibling, card)
    renumberSteps()
  }
  let dragged = null
  dialogContent.ondragstart = event => { dragged = event.target.closest('.step-editor') }
  dialogContent.ondragover = event => { if (dragged && event.target.closest('.step-editor')) event.preventDefault() }
  dialogContent.ondrop = event => {
    const target = event.target.closest('.step-editor')
    if (dragged && target && dragged !== target) target.parentElement.insertBefore(dragged, target)
    dragged = null
    renumberSteps()
    dialogContent.dispatchEvent(new Event('input',{bubbles:true}))
  }
}
