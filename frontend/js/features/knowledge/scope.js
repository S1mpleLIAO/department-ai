import { $, escapeHtml } from '../../core/dom.js'

function selectedScopeType(prefix) {
  return document.querySelector(`input[name="${prefix}-scope-type"]:checked`)?.value || ''
}

function resolvedScopeType(values) {
  if (Object.hasOwn(values, 'scopeType')) return values.scopeType || ''
  if (values.applicableProcessId && values.applicableStepId) return 'process'
  return values.applicableScenario ? 'task' : 'global'
}

function stepOptions(process, selectedStepId = '') {
  return `<option value="">请选择步骤</option>${(process?.steps || []).map(step => `<option value="${escapeHtml(step.id)}" ${step.id === selectedStepId ? 'selected' : ''}>${escapeHtml(step.name)}</option>`).join('')}`
}

export function scopeFieldsHtml(prefix, processes, values = {}) {
  const scopeType = resolvedScopeType(values)
  const process = processes.find(item => item.id === values.applicableProcessId)
  const checked = type => scopeType === type ? 'checked' : ''
  return `<fieldset class="scope-fieldset field full">
    <legend>适用范围</legend>
    <div class="scope-options">
      <label class="check-field" for="${prefix}-scope-global"><input id="${prefix}-scope-global" name="${prefix}-scope-type" type="radio" value="global" ${checked('global')}>全局通用</label>
      <label class="check-field" for="${prefix}-scope-task"><input id="${prefix}-scope-task" name="${prefix}-scope-type" type="radio" value="task" ${checked('task')}>独立任务场景</label>
      <label class="check-field" for="${prefix}-scope-process"><input id="${prefix}-scope-process" name="${prefix}-scope-type" type="radio" value="process" ${checked('process')}>业务流程步骤</label>
    </div>
    <div class="form-grid inset" id="${prefix}-task-fields" ${scopeType === 'task' ? '' : 'hidden'}>
      <div class="field full"><label for="${prefix}-task-scenario">任务场景</label><input id="${prefix}-task-scenario" value="${escapeHtml(values.applicableScenario || '')}" placeholder="例如：编写设计方案"></div>
    </div>
    <div class="form-grid inset" id="${prefix}-process-fields" ${scopeType === 'process' ? '' : 'hidden'}>
      <div class="field"><label for="${prefix}-process">业务流程</label><select id="${prefix}-process"><option value="">请选择流程</option>${processes.map(item => `<option value="${escapeHtml(item.id)}" ${item.id === values.applicableProcessId ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="${prefix}-step">流程步骤</label><select id="${prefix}-step">${stepOptions(process, values.applicableStepId)}</select></div>
    </div>
  </fieldset>`
}

export function bindScopeFields(prefix, processes) {
  const selectedType = () => document.querySelector(`input[name="${prefix}-scope-type"]:checked`)?.value || ''
  const refreshVisibility = () => {
    document.querySelector(`#${prefix}-task-fields`).hidden = selectedType() !== 'task'
    document.querySelector(`#${prefix}-process-fields`).hidden = selectedType() !== 'process'
  }
  document.querySelectorAll(`input[name="${prefix}-scope-type"]`).forEach(control => control.addEventListener('change', refreshVisibility))
  $(`#${prefix}-process`).addEventListener('change', event => {
    const process = processes.find(item => item.id === event.currentTarget.value)
    $(`#${prefix}-step`).innerHTML = stepOptions(process)
  })
  refreshVisibility()
}

export function collectScope(prefix) {
  const scopeType = selectedScopeType(prefix)
  return {
    scopeType,
    applicableProcessId: scopeType === 'process' ? $(`#${prefix}-process`).value : '',
    applicableStepId: scopeType === 'process' ? $(`#${prefix}-step`).value : '',
    applicableScenario: scopeType === 'task' ? $(`#${prefix}-task-scenario`).value.trim() : '',
  }
}

export function validateScope(prefix) {
  const scopeType = selectedScopeType(prefix)
  if (!scopeType) return $(`#${prefix}-scope-global`)
  if (scopeType === 'task' && !$(`#${prefix}-task-scenario`).value.trim()) return $(`#${prefix}-task-scenario`)
  if (scopeType === 'process' && !$(`#${prefix}-process`).value) return $(`#${prefix}-process`)
  if (scopeType === 'process' && !$(`#${prefix}-step`).value) return $(`#${prefix}-step`)
}

export function applyScope(prefix, metadata, processes) {
  const controls = [...document.querySelectorAll(`input[name="${prefix}-scope-type"]`)]
  controls.forEach(control => {
    control.checked = false
    delete control.dataset.aiSuggested
  })
  const dependentControls = [$(`#${prefix}-task-scenario`), $(`#${prefix}-process`), $(`#${prefix}-step`)]
  dependentControls.forEach(control => {
    control.value = ''
    delete control.dataset.aiSuggested
  })
  $(`#${prefix}-process`).dispatchEvent(new Event('change', { bubbles: true }))
  const scopeType = metadata?.suggestedScopeType || metadata?.scopeType || ''
  if (scopeType === 'process') {
    const process = processes.find(item => item.id === metadata.applicableProcessId)
    const step = process?.steps.find(item => item.id === metadata.applicableStepId)
    if (!process || !step) {
      controls[0].dispatchEvent(new Event('change', { bubbles: true }))
      return
    }
    $(`#${prefix}-process`).value = process.id
    $(`#${prefix}-process`).dispatchEvent(new Event('change', { bubbles: true }))
    $(`#${prefix}-step`).value = step.id
    $(`#${prefix}-process`).dataset.aiSuggested = 'true'
    $(`#${prefix}-step`).dataset.aiSuggested = 'true'
  } else if (scopeType === 'task') {
    $(`#${prefix}-task-scenario`).value = metadata.applicableScenario || ''
    if (metadata.applicableScenario) $(`#${prefix}-task-scenario`).dataset.aiSuggested = 'true'
  } else if (scopeType !== 'global') {
    controls[0].dispatchEvent(new Event('change', { bubbles: true }))
    return
  }
  const selected = $(`#${prefix}-scope-${scopeType}`)
  selected.checked = true
  selected.dataset.aiSuggested = 'true'
  selected.dispatchEvent(new Event('change', { bubbles: true }))
}

export function scopeLabel(document, processes) {
  const scopeType = resolvedScopeType(document)
  if (scopeType === 'task') return `独立任务 / ${document.applicableScenario || '未填写场景'}`
  if (scopeType === 'process') {
    const process = processes.find(item => item.id === document.applicableProcessId)
    const step = process?.steps.find(item => item.id === document.applicableStepId)
    return process && step ? `${process.name} / ${step.name}` : '业务流程步骤'
  }
  return '全局通用'
}
