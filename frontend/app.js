const $ = (selector, root = document) => root.querySelector(selector)
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)]
const content = $('#content')
const pageTitle = $('#page-title')
const pageSubtitle = $('#page-subtitle')
const pageAction = $('#page-action')
const pageSecondaryAction = $('#page-secondary-action')
const assistantHost = $('#assistant-host')
const dialog = $('#editor-dialog')
const dialogContent = $('#dialog-content')
const dialogSave = $('#dialog-save')
const confirmDialog = $('#confirm-dialog')
const confirmMessage = $('#confirm-message')
const confirmDetail = $('#confirm-detail')
const dialogCloseDelay = 180

function showAnimatedDialog(node) {
  node.classList.remove('is-open', 'is-closing')
  node.showModal()
  const nextFrame = window.requestAnimationFrame || (callback => setTimeout(callback, 0))
  nextFrame(() => node.classList.add('is-open'))
}

function closeAnimatedDialog(node, returnValue = '') {
  if (!node.open) return Promise.resolve()
  if (node.closePromise) return node.closePromise
  node.classList.remove('is-open')
  node.classList.add('is-closing')
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  node.closePromise = new Promise(resolve => {
    setTimeout(() => {
      node.close(returnValue)
      node.classList.remove('is-closing')
      node.closePromise = null
      resolve()
    }, reducedMotion ? 0 : dialogCloseDelay)
  })
  return node.closePromise
}

$$('.dialog-close', dialog).forEach(button => button.onclick = () => void closeAnimatedDialog(dialog))
dialog.addEventListener('cancel', event => { event.preventDefault(); void closeAnimatedDialog(dialog) })
confirmDialog.addEventListener('cancel', event => { event.preventDefault(); void closeAnimatedDialog(confirmDialog, 'cancel') })
$$('button[value]', confirmDialog).forEach(button => button.onclick = event => {
  event.preventDefault()
  void closeAnimatedDialog(confirmDialog, button.value)
})
let generatedControlId = 0

let state = { processes: [], categories: [], purposes: [], documents: [], skills: [], settings: null, services: {} }
let activeCategory = ''
const collapsedCategories = new Set()

const pageInfo = {
  dashboard: ['工作台', '流程规则、知识资产和 AI 服务概览'],
  processes: ['业务流程', '在流程步骤中定义输入、交付物和完成标准'],
  knowledge: ['知识库', '管理目录、文档模板、版本和向量索引'],
  skills: ['技能', '管理特殊任务的专业执行规则'],
  assistant: ['AI 助手', '上传当前任务文件，让 AI 判断流程并检索真实模板'],
  settings: ['系统设置', '配置助手规则、分块、召回和推荐策略'],
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])
}

function lines(value = []) { return value.join('\n') }
function lineValues(value = '') { return value.split('\n').map(item => item.trim()).filter(Boolean) }
function formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '—' }
function statusLabel(value) { return ({ draft: '草稿', effective: '有效', obsolete: '已废止' })[value] || value }
function purposeLabel(value) { return state.purposes.find(item => item.id === value)?.name || value || '未设置' }
function resourceUrl(skillId, path) { return `/api/skills/${encodeURIComponent(skillId)}/resources/${path.split('/').map(encodeURIComponent).join('/')}` }
function formatBytes(size = 0) { return size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KiB` : `${(size / 1024 / 1024).toFixed(1)} MiB` }
function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768))
  return btoa(binary)
}

async function api(action, body = {}) {
  let method = 'GET'
  let path = '/api/state'
  let payload
  if (action === 'process/save') {
    method = state.processes.some(item => item.id === body.id) ? 'PUT' : 'POST'
    path = method === 'PUT' ? `/api/processes/${encodeURIComponent(body.id)}` : '/api/processes'
    payload = body
  } else if (action === 'process/delete') {
    method = 'DELETE'; path = `/api/processes/${encodeURIComponent(body.id)}`
  } else if (action === 'category/save') {
    method = body.create ? 'POST' : 'PUT'
    path = body.create ? '/api/categories' : `/api/categories/${encodeURIComponent(body.id)}`
    payload = { name: body.name, parentId: body.parentId || null }
  } else if (action === 'category/delete') {
    method = 'DELETE'; path = `/api/categories/${encodeURIComponent(body.id)}`
  } else if (action === 'purpose/save') {
    method = body.id ? 'PUT' : 'POST'
    path = body.id ? `/api/purposes/${encodeURIComponent(body.id)}` : '/api/purposes'
    payload = { ...body }; delete payload.id
  } else if (action === 'purpose/delete') {
    method = 'DELETE'; path = `/api/purposes/${encodeURIComponent(body.id)}`
  } else if (action === 'knowledge/preview') {
    method = 'POST'; path = '/api/knowledge/preview'; payload = body
  } else if (action === 'knowledge/rechunk') {
    method = 'POST'; path = `/api/knowledge/previews/${encodeURIComponent(body.previewId)}/rechunk`; payload = body.chunkSettings
  } else if (action === 'knowledge/index') {
    method = 'POST'; path = `/api/knowledge/previews/${encodeURIComponent(body.previewId)}/index`; payload = { ...body }; delete payload.previewId
  } else if (action === 'knowledge/get') {
    path = `/api/documents/${encodeURIComponent(body.id)}`
  } else if (action === 'knowledge/delete') {
    method = 'DELETE'; path = `/api/documents/${encodeURIComponent(body.id)}`
  } else if (action === 'knowledge/update') {
    method = 'PUT'; path = `/api/documents/${encodeURIComponent(body.id)}`; payload = { ...body }; delete payload.id
  } else if (action === 'knowledge/reindex') {
    method = 'POST'; path = `/api/documents/${encodeURIComponent(body.id)}/reindex`
  } else if (action === 'knowledge/preview-delete') {
    method = 'DELETE'; path = `/api/knowledge/previews/${encodeURIComponent(body.previewId)}`
  } else if (action === 'settings/save') {
    method = 'PUT'; path = '/api/settings'; payload = body
  } else if (action === 'skill/save') {
    method = body.id ? 'PUT' : 'POST'
    path = body.id ? `/api/skills/${encodeURIComponent(body.id)}` : '/api/skills'
    payload = { ...body }; delete payload.id
  } else if (action === 'skill/delete') {
    method = 'DELETE'; path = `/api/skills/${encodeURIComponent(body.id)}`
  } else if (action === 'skill/resource-save') {
    method = 'PUT'; path = resourceUrl(body.skillId, body.path); payload = { contentBase64: body.contentBase64 }
  } else if (action === 'skill/resource-delete') {
    method = 'DELETE'; path = resourceUrl(body.skillId, body.path)
  }
  const response = await fetch(path, {
    method,
    headers: payload === undefined ? undefined : { 'content-type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  const responsePayload = await response.json()
  if (!response.ok) {
    const detail = Array.isArray(responsePayload.detail) ? responsePayload.detail.map(item => item.msg).join('；') : responsePayload.detail
    throw new Error(detail || responsePayload.error || '请求失败')
  }
  return responsePayload
}

async function refresh() { state = await api('state') }

function toast(message, error = false) {
  const node = $('#toast')
  node.textContent = message
  node.className = `toast show${error ? ' error' : ''}`
  if (node.showPopover && !node.matches(':popover-open')) node.showPopover()
  clearTimeout(toast.timer)
  toast.timer = setTimeout(() => {
    node.className = 'toast'
    if (node.hidePopover && node.matches(':popover-open')) node.hidePopover()
  }, 3000)
}

function bindFormLabels(root) {
  $$('.field', root).forEach(field => {
    const label = $('label', field)
    const control = $('input:not([type="hidden"]), textarea, select', field)
    if (!label || !control) return
    if (!control.id) control.id = `field-control-${++generatedControlId}`
    label.htmlFor = control.id
  })
}

function clearFieldError(control) {
  control.removeAttribute('aria-invalid')
  const error = control.closest('.field')?.querySelector('.field-error')
  if (error) error.remove()
}

function validateDialogForm() {
  const controls = $$('input, textarea, select', dialog).filter(control => !control.disabled && control.type !== 'hidden')
  controls.forEach(clearFieldError)
  const invalid = controls.find(control => !control.checkValidity())
  if (!invalid) return true
  invalid.setAttribute('aria-invalid', 'true')
  const field = invalid.closest('.field')
  if (field) {
    const label = $('label', field)?.textContent.trim() || '此字段'
    const error = document.createElement('small')
    error.className = 'field-error'
    error.textContent = invalid.validity.valueMissing ? `请填写${label}` : `请检查${label}的格式`
    field.append(error)
  }
  invalid.focus()
  return false
}

function confirmAction(message, detail = '') {
  const trigger = document.activeElement
  confirmMessage.textContent = message
  confirmDetail.textContent = detail
  confirmDetail.hidden = !detail
  confirmDialog.returnValue = 'cancel'
  return new Promise(resolve => {
    confirmDialog.addEventListener('close', () => {
      if (trigger instanceof HTMLElement) trigger.focus()
      resolve(confirmDialog.returnValue === 'confirm')
    }, { once: true })
    showAnimatedDialog(confirmDialog)
  })
}

function setAction(label, handler) {
  pageAction.hidden = !label
  pageAction.textContent = label || ''
  pageAction.onclick = handler || null
}

function setSecondaryAction(label, handler) {
  pageSecondaryAction.hidden = !label
  pageSecondaryAction.textContent = label || ''
  pageSecondaryAction.onclick = handler || null
}

function openDialog(title, subtitle, html, onSave, options = {}) {
  const trigger = document.activeElement
  $('#dialog-title').textContent = title
  $('#dialog-subtitle').textContent = subtitle
  dialogContent.innerHTML = html
  bindFormLabels(dialogContent)
  dialogContent.oninput = event => {
    if (event.target.matches('input, textarea, select')) clearFieldError(event.target)
  }
  dialog.classList.toggle('wide', options.wide === true)
  dialog.classList.toggle('skill-dialog', options.kind === 'skill')
  dialogSave.hidden = options.readOnly === true
  dialogSave.disabled = false
  dialogSave.textContent = options.saveLabel || '保存'
  dialogSave.onclick = async (event) => {
    event.preventDefault()
    if (!validateDialogForm()) return
    dialogSave.disabled = true
    try {
      await onSave()
      await closeAnimatedDialog(dialog)
      await refresh()
      renderPage()
      toast(options.successMessage || '已保存')
    } catch (error) {
      toast(error.message, true)
    } finally {
      dialogSave.disabled = false
    }
  }
  dialog.addEventListener('close', () => {
    if (!dialog.open && !confirmDialog.open && trigger instanceof HTMLElement) trigger.focus()
  }, { once: true })
  showAnimatedDialog(dialog)
}

function serviceBadge(ok, label) {
  return `<span class="service-badge ${ok ? 'ok' : 'off'}"><i></i>${label}</span>`
}

function renderDashboard() {
  const steps = state.processes.reduce((sum, process) => sum + process.steps.length, 0)
  const templates = state.documents.filter(item => item.isGenerationTemplate && item.status === 'effective').length
  const indexed = state.documents.filter(item => item.indexed).length
  content.innerHTML = `
    <div class="hero">
      <div><span class="hero-eyebrow">部门任务入口</span><h2>让 AI 先查真实模板，再开始生成</h2><p>业务要求定义在流程步骤中；合同、方案和历史文件进入知识库。AI 只会推荐知识库中实际存在的模板和变体。</p></div>
      <a class="button" href="#assistant">开始与 AI 对话 →</a>
    </div>
    <div class="stats">
      <div class="stat-card"><span>业务流程</span><strong>${state.processes.length}</strong></div>
      <div class="stat-card"><span>流程步骤</span><strong>${steps}</strong></div>
      <div class="stat-card"><span>有效生成模板</span><strong>${templates}</strong></div>
      <div class="stat-card"><span>已建立索引文档</span><strong>${indexed}</strong></div>
    </div>
    <div class="service-strip">
      <b>服务状态</b>
      ${serviceBadge(state.services.database, 'PostgreSQL / pgvector')}
      ${serviceBadge(state.services.docling, 'Docling')}
      ${serviceBadge(state.services.siliconflow, 'Embedding / Rerank 已配置')}
      ${serviceBadge(state.services.harness, 'DeepSeek Harness')}
    </div>
    <div class="section-heading"><div><h2>下一步</h2><p>先配置标准，再交给 AI 使用</p></div></div>
    <div class="quick-grid">
      <a href="#processes" class="quick-card"><b>维护业务流程</b><span>定义每一步需要什么、完成什么、做到什么程度。</span></a>
      <a href="#knowledge" class="quick-card"><b>上传知识与模板</b><span>解析文档、预览分块，并标记模板家族、变体和版本。</span></a>
      <a href="#settings" class="quick-card"><b>调整检索设置</b><span>设置分块大小、召回数量、重排序数量和模板推荐数。</span></a>
    </div>`
}

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

function openProcessEditor(process) {
  const current = process || { id: '', name: '', description: '', steps: [{}] }
  openDialog(process ? '编辑业务流程' : '新建业务流程', '任务要求直接定义在流程步骤中，不再单独维护任务模板', `
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
      await api('process/save', { id: process?.id, name: $('#process-name').value.trim(), description: $('#process-description').value.trim(), steps })
    }, { wide: true })
  $('#add-step').onclick = () => { $('.steps-editor').insertAdjacentHTML('beforeend', stepEditor({}, $$('.step-editor').length)); renumberSteps() }
  dialogContent.onclick = event => {
    const card = event.target.closest('.step-editor')
    if (!card) return
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
  }
}

function renderProcesses() {
  setAction('+ 新建流程', () => openProcessEditor())
  content.innerHTML = state.processes.length ? `<div class="process-list">${state.processes.map(process => `
    <article class="item-card process-card">
      <div class="item-head"><div><h3>${escapeHtml(process.name)}</h3><p>${escapeHtml(process.description)}</p></div><div class="actions"><button class="button small edit-process" data-id="${process.id}">编辑</button><button class="button small danger delete-process" data-id="${process.id}">删除</button></div></div>
      <div class="timeline">${process.steps.map((step, index) => `<div class="step-card"><small>第 ${index + 1} 步</small><b>${escapeHtml(step.name)}</b><p>${escapeHtml(step.objective)}</p><div class="meta"><span>${step.requiredInputs.length} 项输入</span><span>${step.requiredOutputs.length} 个交付物</span><span>${step.completionCriteria.length} 项标准</span></div></div>`).join('')}</div>
    </article>`).join('')}</div>` : '<div class="empty">还没有业务流程</div>'
  $$('.edit-process').forEach(button => button.onclick = () => openProcessEditor(state.processes.find(item => item.id === button.dataset.id)))
  $$('.delete-process').forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个业务流程吗？', '流程及其全部步骤会被删除，此操作无法撤销。')) return
    try { await api('process/delete', { id: button.dataset.id }); await refresh(); renderPage(); toast('已删除') } catch (error) { toast(error.message, true) }
  })
}

function categoryOptions(selected = '', exclude = '') {
  const children = parent => state.categories.filter(item => (item.parentId || '') === parent)
  const rows = []
  const visit = (parent, depth) => children(parent).forEach(item => {
    if (item.id === exclude) return
    rows.push(`<option value="${item.id}" ${item.id === selected ? 'selected' : ''}>${'　'.repeat(depth)}${escapeHtml(item.name)}</option>`)
    visit(item.id, depth + 1)
  })
  visit('', 0)
  return rows.join('')
}

function categoryTree() {
  const children = parent => state.categories.filter(item => (item.parentId || '') === parent)
  const documentCount = id => {
    const ids = new Set([id])
    const collect = parent => children(parent).forEach(item => { ids.add(item.id); collect(item.id) })
    collect(id)
    return state.documents.filter(item => item.categoryId && ids.has(item.categoryId)).length
  }
  const visit = (parent, depth) => children(parent).map(item => {
    const hasChildren = children(item.id).length > 0
    const collapsed = collapsedCategories.has(item.id)
    return `<div class="category-row ${activeCategory === item.id ? 'active' : ''}" style="--depth:${depth}">
      <button class="category-toggle" data-id="${item.id}" ${hasChildren ? `aria-label="${collapsed ? '展开' : '收起'}${escapeHtml(item.name)}"` : 'disabled aria-hidden="true"'}>${hasChildren ? (collapsed ? '▸' : '▾') : '·'}</button>
      <button class="category-select" data-id="${item.id}"><span>${escapeHtml(item.name)}</span><small>${documentCount(item.id)}</small></button>
      <button class="category-edit" data-id="${item.id}" aria-label="编辑${escapeHtml(item.name)}目录" title="编辑目录">•••</button>
    </div>${hasChildren && !collapsed ? visit(item.id, depth + 1) : ''}`
  }).join('')
  return visit('', 0)
}

function openCategoryEditor(category) {
  const current = category || { parentId: activeCategory || '', name: '' }
  openDialog(category ? '编辑知识目录' : '新建知识目录', '目录可以随时新增、重命名和移动', `
    <div class="form-grid">
      <div class="field full"><label>目录名称</label><input id="category-name" value="${escapeHtml(current.name)}" placeholder="网络"></div>
      <div class="field"><label>上级目录</label><select id="category-parent"><option value="">根目录</option>${categoryOptions(current.parentId || '', current.id)}</select></div>
      <p class="muted small-copy">新目录会自动排在同级目录末尾；移动目录时，下面的子目录和文档会一起保留。</p>
    </div>
    ${category ? '<div class="danger-zone"><b>删除目录</b><span>只有没有子目录和文档时才能删除。</span><button type="button" id="delete-category" class="button danger">删除</button></div>' : ''}`, async () => {
      const result = await api('category/save', { id: category?.id || '', create: !category, name: $('#category-name').value.trim(), parentId: $('#category-parent').value })
      activeCategory = result.category.id
    })
  if (category) $('#delete-category').onclick = async () => {
    if (!await confirmAction('确定删除这个目录吗？', '只有空目录可以删除。')) return
    try { await api('category/delete', { id: category.id }); await closeAnimatedDialog(dialog); activeCategory = ''; await refresh(); renderPage(); toast('目录已删除') } catch (error) { toast(error.message, true) }
  }
}

function chunkSettingsForm(settings) {
  return `<div class="chunk-settings">
    <div class="field"><label>切块方式</label><select id="chunk-mode"><option value="structure" ${settings.mode === 'structure' ? 'selected' : ''}>智能结构</option><option value="general" ${settings.mode === 'general' ? 'selected' : ''}>通用分隔符</option><option value="parent-child" ${settings.mode === 'parent-child' ? 'selected' : ''}>父子分块</option></select></div>
    <div class="field general-setting"><label>分段标识符</label><input id="chunk-delimiter" value="${escapeHtml(settings.delimiter.replaceAll('\n', '\\n'))}" placeholder="\\n\\n 表示空行"></div>
    <div class="field standard-setting"><label>每块最大 Token</label><input id="chunk-max" type="number" min="100" value="${settings.maxTokens}"></div>
    <div class="field standard-setting"><label>重叠 Token</label><input id="chunk-overlap" type="number" min="0" value="${settings.overlapTokens}"></div>
    <div class="field parent-setting"><label>父块最大 Token</label><input id="parent-max" type="number" min="300" value="${settings.parentMaxTokens}"></div>
    <div class="field parent-setting"><label>子块最大 Token</label><input id="child-max" type="number" min="100" value="${settings.childMaxTokens}"></div>
    <div class="field parent-setting"><label>子块重叠 Token</label><input id="child-overlap" type="number" min="0" value="${settings.childOverlapTokens}"></div>
    <label class="check-field"><input id="clean-whitespace" type="checkbox" ${settings.cleanWhitespace ? 'checked' : ''}> 合并连续空格和多余换行</label>
    <label class="check-field"><input id="remove-urls" type="checkbox" ${settings.removeUrlsEmails ? 'checked' : ''}> 删除 URL 和邮箱地址</label>
  </div>`
}

function collectChunkSettings() {
  return {
    mode: $('#chunk-mode').value,
    delimiter: $('#chunk-delimiter').value.replaceAll('\\n', '\n'),
    maxTokens: Number($('#chunk-max').value),
    overlapTokens: Number($('#chunk-overlap').value),
    parentMaxTokens: Number($('#parent-max').value),
    childMaxTokens: Number($('#child-max').value),
    childOverlapTokens: Number($('#child-overlap').value),
    cleanWhitespace: $('#clean-whitespace').checked,
    removeUrlsEmails: $('#remove-urls').checked,
  }
}

function setChunkSettings(settings) {
  $('#chunk-mode').value = settings.mode
  $('#chunk-delimiter').value = settings.delimiter.replaceAll('\n', '\\n')
  $('#chunk-max').value = settings.maxTokens
  $('#chunk-overlap').value = settings.overlapTokens
  $('#parent-max').value = settings.parentMaxTokens
  $('#child-max').value = settings.childMaxTokens
  $('#child-overlap').value = settings.childOverlapTokens
  $('#clean-whitespace').checked = settings.cleanWhitespace
  $('#remove-urls').checked = settings.removeUrlsEmails
  toggleChunkFields()
}

function chunkModeLabel(value) { return ({ structure: '智能结构', general: '通用分隔符', 'parent-child': '父子分块' })[value] || value }

function purposeChunkSummary(purpose) {
  if (!purpose.chunkBody) return '不建立正文分块'
  if (purpose.inheritChunking) return '继承系统默认分块设置'
  return chunkSettingsSummary(purpose.chunkSettings)
}

function chunkSettingsSummary(settings) {
  const preprocessing = [settings.cleanWhitespace ? '合并空格与多余换行' : '', settings.removeUrlsEmails ? '删除 URL 与邮箱' : '保留 URL 与邮箱'].filter(Boolean).join(' · ')
  return settings.mode === 'parent-child'
    ? `${chunkModeLabel(settings.mode)} · 父块 ${settings.parentMaxTokens} Token · 子块 ${settings.childMaxTokens} Token · 子块重叠 ${settings.childOverlapTokens} Token · ${preprocessing}`
    : `${chunkModeLabel(settings.mode)} · 每块最大 ${settings.maxTokens} Token · 重叠 ${settings.overlapTokens} Token · ${preprocessing}`
}

function togglePurposeEditor() {
  const chunkBody = $('#purpose-chunk-body').checked
  $('#purpose-chunk-options').hidden = !chunkBody
  $('#purpose-custom-chunk').hidden = !chunkBody || $('#purpose-inherit-chunking').checked
}

function openPurposeEditor(purpose) {
  const current = purpose || {
    name: '', description: '', canGenerateTemplate: false, chunkBody: true,
    inheritChunking: true, chunkSettings: state.settings.chunking,
  }
  openDialog(purpose ? '编辑文档用途' : '新增文档用途', '用途决定文档能否作为模板，以及正文是否建立分块索引。', `
    <div class="purpose-form">
      <section class="purpose-section">
        <div class="form-grid">
          <div class="field"><label>用途名称</label><input id="purpose-name" value="${escapeHtml(current.name)}" placeholder="例如：历史设计方案" required></div>
          <div class="field"><label>用途说明</label><input id="purpose-description" value="${escapeHtml(current.description)}" placeholder="说明什么文档应该选择这个用途"></div>
        </div>
      </section>
      <section class="purpose-section"><h3>索引能力</h3><p class="muted">至少选择一项；标题、摘要、关键词、完整正文和原始文件始终保存。</p>
        <div class="purpose-capabilities">
          <label class="purpose-capability"><input id="purpose-template" type="checkbox" ${current.canGenerateTemplate ? 'checked' : ''}><span><b>可作为生成模板</b><small>AI推荐整份模板，用户确认后读取完整正文。</small></span></label>
          <label class="purpose-capability"><input id="purpose-chunk-body" type="checkbox" ${current.chunkBody ? 'checked' : ''}><span><b>建立正文分块索引</b><small>AI可以检索真实章节、条款和父块上下文。</small></span></label>
        </div>
      </section>
      <section class="purpose-section" id="purpose-chunk-options"><h3>默认分块规则</h3>
        <label class="check-field purpose-inherit"><input id="purpose-inherit-chunking" type="checkbox" ${current.inheritChunking ? 'checked' : ''}> 继承系统默认分块设置</label>
        <div class="purpose-default-summary"><b>当前系统默认</b><span>${escapeHtml(chunkSettingsSummary(state.settings.chunking))}</span></div>
        <div id="purpose-custom-chunk">${chunkSettingsForm(current.chunkSettings || state.settings.chunking)}</div>
      </section>
      ${purpose?.documentCount ? `<p class="purpose-note">当前有 ${purpose.documentCount} 份文档使用此用途。修改索引能力和分块默认值只影响以后上传的文档，不会静默重建已有索引。</p>` : ''}
    </div>`, async () => {
      await api('purpose/save', {
        id: purpose?.id,
        name: $('#purpose-name').value.trim(),
        description: $('#purpose-description').value.trim(),
        canGenerateTemplate: $('#purpose-template').checked,
        chunkBody: $('#purpose-chunk-body').checked,
        inheritChunking: $('#purpose-inherit-chunking').checked,
        chunkSettings: collectChunkSettings(),
      })
    }, { wide: true, successMessage: purpose ? '文档用途已更新' : '文档用途已创建' })
  toggleChunkFields()
  togglePurposeEditor()
  $('#purpose-chunk-body').onchange = togglePurposeEditor
  $('#purpose-inherit-chunking').onchange = event => {
    if (!event.target.checked) setChunkSettings(state.settings.chunking)
    togglePurposeEditor()
  }
  $('#chunk-mode').onchange = toggleChunkFields
}

function purposeManagerHtml() {
  return `<div class="purpose-manager-heading"><p>用途决定文档能否作为整份模板，以及正文是否建立分块索引。</p><button type="button" class="button primary" id="add-purpose">+ 新增用途</button></div><div class="purpose-list">${state.purposes.map(purpose => `
    <article class="item-card purpose-card">
      <div class="item-head"><div><div class="title-line"><h3>${escapeHtml(purpose.name)}</h3><span class="tag">${purpose.documentCount} 份文档</span></div><p>${escapeHtml(purpose.description || '未填写用途说明')}</p></div>
        <div class="actions"><button class="button small edit-purpose" data-id="${purpose.id}">编辑</button><button class="button small danger delete-purpose" data-id="${purpose.id}">删除</button></div></div>
      <div class="purpose-badges"><span class="${purpose.canGenerateTemplate ? 'enabled' : ''}">整份模板推荐</span><span class="${purpose.chunkBody ? 'enabled' : ''}">正文分块检索</span></div>
      <div class="purpose-rule"><b>分块规则</b><span>${escapeHtml(purposeChunkSummary(purpose))}</span></div>
    </article>`).join('')}</div>`
}

function bindPurposeManager() {
  $('#add-purpose', dialogContent).onclick = () => void closeAnimatedDialog(dialog).then(() => openPurposeEditor())
  $$('.edit-purpose', dialogContent).forEach(button => button.onclick = () => void closeAnimatedDialog(dialog).then(() => openPurposeEditor(state.purposes.find(item => item.id === button.dataset.id))))
  $$('.delete-purpose', dialogContent).forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个文档用途吗？', '正在被文档使用的用途不会被删除。')) return
    try { await api('purpose/delete', { id: button.dataset.id }); await refresh(); dialogContent.innerHTML = purposeManagerHtml(); bindPurposeManager(); toast('文档用途已删除') }
    catch (error) { toast(error.message, true) }
  })
}

function openPurposeManager() {
  openDialog('管理文档用途', '在上传文档前维护用途和对应的索引规则。', purposeManagerHtml(), async () => {}, { wide: true, readOnly: true })
  bindPurposeManager()
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function renderChunkPreview(chunks) {
  const target = $('#chunk-preview')
  const parentMode = $('#chunk-mode')?.value === 'parent-child'
  target.innerHTML = chunks.map(chunk => `<article class="chunk-card ${chunk.enabled ? '' : 'disabled'}" data-index="${chunk.index}" data-parent="${chunk.parentIndex ?? ''}">
    <header><label><input class="chunk-enabled" type="checkbox" ${chunk.enabled ? 'checked' : ''} ${parentMode && chunk.parentIndex === null ? 'disabled' : ''}> ${parentMode && chunk.parentIndex === null ? '父块上下文' : parentMode ? '子块检索' : '使用'}</label><span>${escapeHtml(chunk.sectionPath || '正文')} · 约 ${chunk.tokenCount} tokens${chunk.parentIndex === null ? '' : ` · 父块 #${chunk.parentIndex + 1}`}</span></header>
    <textarea class="chunk-content">${escapeHtml(chunk.content)}</textarea>
  </article>`).join('')
  $$('.chunk-enabled', target).forEach(input => input.onchange = () => input.closest('.chunk-card').classList.toggle('disabled', !input.checked))
}

function collectPreviewChunks() {
  return $$('.chunk-card', $('#chunk-preview')).map(card => ({
    parentIndex: card.dataset.parent === '' ? null : Number(card.dataset.parent),
    sectionPath: $('header span', card).textContent.split(' · ')[0],
    content: $('.chunk-content', card).value,
    enabled: $('.chunk-enabled', card).checked,
  }))
}

function toggleDocumentPurpose() {
  const purpose = state.purposes.find(item => item.id === $('#document-purpose').value)
  if (!purpose) return
  $('#template-fields').hidden = !purpose.canGenerateTemplate
  $('#chunk-fields').hidden = !purpose.chunkBody
  $('#template-family').required = purpose.canGenerateTemplate
  $('#preview-button').textContent = purpose.chunkBody ? '解析、分析并预览分块' : '解析并自动分析'
  $('#index-plan').innerHTML = `<b>将建立的索引</b><span>文档目录索引（标题、摘要、关键词和正文摘要）</span>${purpose.canGenerateTemplate ? '<span>整份模板推荐索引</span>' : ''}${purpose.chunkBody ? '<span>正文分块索引</span>' : '<span>正文不切块，完整正文仍会保存</span>'}`
}

function toggleChunkFields() {
  const mode = $('#chunk-mode').value
  $$('.standard-setting').forEach(node => node.hidden = mode === 'parent-child')
  $$('.parent-setting').forEach(node => node.hidden = mode !== 'parent-child')
  $$('.general-setting').forEach(node => node.hidden = mode !== 'general')
}

function applyMetadataSuggestion(metadata) {
  if (!metadata) return
  const setIfPresent = (selector, value) => { if (value) $(selector).value = value }
  setIfPresent('#document-title', metadata.title)
  setIfPresent('#document-type', metadata.documentType)
  setIfPresent('#document-summary', metadata.summary)
  setIfPresent('#document-keywords', (metadata.keywords || []).join('、'))
  setIfPresent('#template-family', metadata.templateFamily)
  setIfPresent('#template-variant', metadata.templateVariant)
  setIfPresent('#template-version', metadata.version)
  setIfPresent('#template-scenario', metadata.applicableScenario)
  toggleDocumentPurpose()
}

function openKnowledgeUpload() {
  const chunking = state.settings.chunking
  const defaultPurpose = state.purposes.find(item => item.id === 'reference-knowledge') || state.purposes[0]
  let preview = null
  const discardPreview = async () => {
    if (!preview) return
    const previewId = preview.id
    preview = null
    try { await api('knowledge/preview-delete', { previewId }) } catch (_) {}
  }
  openDialog('知识入库', '解析正文 → AI建议元数据 → 人工确认 → 按用途建立索引', `
    <div class="upload-stepper" aria-label="知识入库步骤">
      <span class="current"><b>1</b>选择文件与属性</span><i aria-hidden="true"></i>
      <span><b>2</b>解析与调整分块</span><i aria-hidden="true"></i>
      <span><b>3</b>确认并建立索引</span>
    </div>
    <div class="upload-workflow">
      <section class="upload-column">
        <h3>文档与属性</h3>
        <div class="form-grid">
          <div class="field full"><label>选择文件</label><input id="knowledge-file" type="file" accept=".txt,.md,.csv,.json,.docx,.pdf,.pptx,.xlsx"></div>
          <div class="field"><label>文档 ID</label><input id="document-id" value="knowledge-${Date.now()}" placeholder="purchase-contract-v2" pattern="[a-z0-9][a-z0-9-]{0,63}" required></div>
          <div class="field"><label>文档标题</label><input id="document-title" required></div>
          <div class="field"><label>文档用途</label><select id="document-purpose">${state.purposes.map(item => `<option value="${item.id}" ${item.id === defaultPurpose?.id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}</select></div>
          <div class="field"><label>文档类型</label><input id="document-type" placeholder="设计方案 / 补充协议"></div>
          <div class="field"><label>知识目录</label><select id="document-category"><option value="">未分类</option>${categoryOptions(activeCategory)}</select></div>
          <div class="field"><label>状态</label><select id="document-status"><option value="effective">有效</option><option value="draft">草稿</option><option value="obsolete">已废止</option></select></div>
          <div class="field full"><label>关键词</label><input id="document-keywords" placeholder="CPU、服务器、采购、补充协议"></div>
          <div class="field full"><label>文档简介</label><textarea id="document-summary" placeholder="说明文档内容和适用范围"></textarea></div>
        </div>
        <div id="template-fields" hidden>
          <div class="form-grid inset">
            <div class="field"><label>模板家族</label><input id="template-family" placeholder="高性能网络组网方案"></div>
            <div class="field"><label>模板变体</label><input id="template-variant" placeholder="RoCE / InfiniBand"></div>
            <div class="field"><label>版本</label><input id="template-version" value="V1.0" placeholder="V1.0"></div>
          </div>
        </div>
        <div class="form-grid inset">
          <div class="field full"><label>适用场景（AI建议，可修改）</label><input id="template-scenario" placeholder="GPU 集群网络"></div>
        </div>
        <div class="index-plan" id="index-plan"></div>
        <div id="chunk-fields"><h3>分块设置</h3>${chunkSettingsForm(chunking)}</div>
        <button type="button" class="button primary" id="preview-button">解析、分析并预览分块</button>
        <p id="metadata-status" class="muted small-copy">AI会自动建议标题、类型、摘要、关键词、用途和模板属性，请在保存前确认。</p>
      </section>
      <section class="preview-column">
        <div class="preview-heading"><div><h3>分块预览</h3><p id="preview-summary">上传文件后在这里检查和编辑</p></div><button type="button" class="button small" id="rechunk-button" hidden>重新切块</button></div>
        <div id="chunk-preview" class="chunk-preview"><div class="empty compact">尚未解析文档</div></div>
      </section>
    </div>`, async () => {
      if (!preview) throw new Error('请先解析并预览文档')
      await api('knowledge/index', {
        previewId: preview.id,
        id: $('#document-id').value.trim(), title: $('#document-title').value.trim(),
        purposeId: $('#document-purpose').value, documentType: $('#document-type').value.trim(),
        keywords: $('#document-keywords').value.split(/[、,，\n]+/).map(item => item.trim()).filter(Boolean),
        outline: preview.metadata?.outline || [],
        categoryId: $('#document-category').value, status: $('#document-status').value,
        summary: $('#document-summary').value.trim(),
        templateFamily: $('#template-family').value.trim(), templateVariant: $('#template-variant').value.trim(),
        version: $('#template-version').value.trim(), applicableScenario: $('#template-scenario').value.trim(),
        chunks: collectPreviewChunks(),
      })
      preview = null
  }, { wide: true, saveLabel: '确认并建立索引', successMessage: '文档已入库并按用途完成索引' })
  dialog.addEventListener('close', () => { void discardPreview() }, { once: true })
  dialogSave.disabled = true
  toggleChunkFields()
  toggleDocumentPurpose()
  setChunkSettings(defaultPurpose?.inheritChunking ? chunking : defaultPurpose?.chunkSettings || chunking)
  $('#document-purpose').onchange = event => {
    const purpose = state.purposes.find(item => item.id === event.target.value)
    setChunkSettings(purpose?.inheritChunking ? state.settings.chunking : purpose?.chunkSettings || state.settings.chunking)
    toggleDocumentPurpose()
  }
  $('#chunk-mode').onchange = toggleChunkFields
  $('#knowledge-file').onchange = event => { if (!$('#document-title').value) $('#document-title').value = event.target.files[0]?.name.replace(/\.[^.]+$/, '') || '' }
  $('#preview-button').onclick = async () => {
    const file = $('#knowledge-file').files[0]
    if (!file) return toast('请先选择文件', true)
    const button = $('#preview-button')
    button.disabled = true
    button.textContent = '正在解析并分析元数据…'
    try {
      await discardPreview()
      preview = await api('knowledge/preview', { fileName: file.name, mimeType: file.type, fileBase64: await fileToBase64(file), chunkSettings: collectChunkSettings() })
      applyMetadataSuggestion(preview.metadata)
      renderChunkPreview(preview.chunks)
      $('#preview-summary').textContent = `${preview.fileName} · ${preview.characters.toLocaleString()} 字符 · ${preview.chunks.length} 块`
      const suggestedPurpose = state.purposes.find(item => item.id === preview.metadata?.suggestedPurposeId)
      $('#metadata-status').textContent = preview.metadataError
        ? `正文解析成功，但AI元数据建议失败：${preview.metadataError}。可以手工填写后保存。`
        : `AI建议已填入${suggestedPurpose ? `，建议用途为“${suggestedPurpose.name}”` : ''}。用途以您上传前的选择为准，请确认其他属性。`
      $('#rechunk-button').hidden = false
      dialogSave.disabled = false
    } catch (error) { toast(error.message, true) } finally { button.disabled = false; toggleDocumentPurpose() }
  }
  $('#rechunk-button').onclick = async () => {
    if (!preview) return
    try {
      preview = await api('knowledge/rechunk', { previewId: preview.id, chunkSettings: collectChunkSettings() })
      renderChunkPreview(preview.chunks)
      $('#preview-summary').textContent = `${preview.characters.toLocaleString()} 字符 · ${preview.chunks.length} 块`
    } catch (error) { toast(error.message, true) }
  }
}

function indexSummary(document) {
  const template = document.isGenerationTemplate ? `<span>${document.documentIndexed ? '模板索引：已建立' : '模板索引：未建立'}</span>` : ''
  const reference = document.isReferenceKnowledge ? `<span>正文索引：${document.chunkIndexed ? `${document.chunkCount} 块` : '未建立'}</span>` : '<span>正文分块：不适用</span>'
  return `<div class="index-summary">${template}${reference}</div>`
}

function openDocumentEditor(detail) {
  openDialog('编辑文档信息', '修改目录和元数据后会自动更新模板目录索引', `
    <div class="form-grid">
      <div class="field"><label>文档标题</label><input id="edit-document-title" value="${escapeHtml(detail.title)}" required></div>
      <div class="field"><label>知识目录</label><select id="edit-document-category"><option value="">未分类</option>${categoryOptions(detail.categoryId || '')}</select></div>
      <div class="field"><label>状态</label><select id="edit-document-status"><option value="effective" ${detail.status === 'effective' ? 'selected' : ''}>有效</option><option value="draft" ${detail.status === 'draft' ? 'selected' : ''}>草稿</option><option value="obsolete" ${detail.status === 'obsolete' ? 'selected' : ''}>已废止</option></select></div>
      <div class="field"><label>文档用途</label><input value="${escapeHtml(detail.purposeName || purposeLabel(detail.purposeId))}" readonly></div>
      <div class="field"><label>文档类型</label><input id="edit-document-type" value="${escapeHtml(detail.documentType)}"></div>
      <div class="field"><label>版本</label><input id="edit-document-version" value="${escapeHtml(detail.version)}" placeholder="V1.0"></div>
      <div class="field full"><label>关键词</label><input id="edit-document-keywords" value="${escapeHtml((detail.keywords || []).join('、'))}"></div>
      ${detail.isGenerationTemplate ? `<div class="field"><label>模板家族</label><input id="edit-template-family" value="${escapeHtml(detail.templateFamily)}" required></div><div class="field"><label>模板变体</label><input id="edit-template-variant" value="${escapeHtml(detail.templateVariant)}"></div>` : '<input id="edit-template-family" type="hidden" value=""><input id="edit-template-variant" type="hidden" value="">'}
      <div class="field full"><label>适用场景</label><input id="edit-document-scenario" value="${escapeHtml(detail.applicableScenario)}"></div>
      <div class="field full"><label>文档简介</label><textarea id="edit-document-summary">${escapeHtml(detail.summary)}</textarea></div>
    </div>`, async () => {
      await api('knowledge/update', {
        id: detail.id,
        title: $('#edit-document-title').value.trim(),
        categoryId: $('#edit-document-category').value || null,
        status: $('#edit-document-status').value,
        documentType: $('#edit-document-type').value.trim(),
        keywords: $('#edit-document-keywords').value.split(/[、,，\n]+/).map(item => item.trim()).filter(Boolean),
        outline: detail.outline || [],
        templateFamily: $('#edit-template-family').value.trim(),
        templateVariant: $('#edit-template-variant').value.trim(),
        version: $('#edit-document-version').value.trim(),
        applicableScenario: $('#edit-document-scenario').value.trim(),
        summary: $('#edit-document-summary').value.trim(),
      })
    }, { wide: true, successMessage: '文档信息和模板索引已更新' })
}

function openDocument(document) {
  api('knowledge/get', { id: document.id }).then(detail => {
    openDialog(detail.title, `${detail.originalName} · ${detail.chunkCount} 个正文分块`, `
      <div class="document-detail">
        <div class="document-actions">
          <button type="button" id="edit-document" class="button">编辑信息</button>
          <a class="button" href="/api/documents/${encodeURIComponent(detail.id)}/source">下载原文件</a>
          <button type="button" id="reindex-document" class="button">重建向量索引</button>
        </div>
        <div class="detail-grid">
          <span><b>状态 / 用途</b>${statusLabel(detail.status)} · ${escapeHtml(detail.purposeName || purposeLabel(detail.purposeId))}</span><span><b>目录</b>${escapeHtml(state.categories.find(item => item.id === detail.categoryId)?.name || '未分类')}</span>
          <span><b>索引状态</b>${indexSummary(detail)}</span><span><b>文档类型</b>${escapeHtml(detail.documentType || '—')}</span>
          <span><b>关键词</b>${escapeHtml((detail.keywords || []).join('、') || '—')}</span><span><b>模板家族</b>${escapeHtml(detail.templateFamily || '—')}</span>
          <span><b>变体 / 版本</b>${escapeHtml([detail.templateVariant, detail.version].filter(Boolean).join(' / ') || '—')}</span><span><b>适用场景</b>${escapeHtml(detail.applicableScenario || '—')}</span>
          <span class="wide"><b>简介</b>${escapeHtml(detail.summary || '—')}</span>
        </div>
        <div class="chunk-preview">${detail.chunks.length ? detail.chunks.map(chunk => `<article class="chunk-card ${chunk.enabled ? '' : 'disabled'}"><header><span>${escapeHtml(chunk.sectionPath || '正文')} · 约 ${chunk.tokenCount} tokens</span></header><div class="chunk-text">${escapeHtml(chunk.content)}</div></article>`).join('') : `<article class="chunk-card"><header><span>完整模板正文 · 选择模板后由 AI 读取</span></header><div class="chunk-text">${escapeHtml(detail.parsedText)}</div></article>`}</div>
        <div class="danger-zone"><b>删除文档</b><span>会同时删除索引、正文和原始文件。</span><button type="button" id="delete-document" class="button danger">删除</button></div>
      </div>`, async () => {}, { wide: true, readOnly: true })
    $('#edit-document').onclick = () => void closeAnimatedDialog(dialog).then(() => openDocumentEditor(detail))
    $('#reindex-document').onclick = async event => {
      const button = event.currentTarget
      button.disabled = true
      button.textContent = '正在重建…'
      try { await api('knowledge/reindex', { id: detail.id }); await closeAnimatedDialog(dialog); await refresh(); renderPage(); toast('向量索引已重建') }
      catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '重建向量索引' }
    }
    $('#delete-document').onclick = async () => {
      if (!await confirmAction('确定删除这个文档吗？', '文档记录、向量索引和受管理的原始文件都会被删除。')) return
      try { await api('knowledge/delete', { id: detail.id }); await closeAnimatedDialog(dialog); await refresh(); renderPage(); toast('文档已删除') } catch (error) { toast(error.message, true) }
    }
  }).catch(error => toast(error.message, true))
}

function renderKnowledge() {
  setAction('+ 上传文档', openKnowledgeUpload)
  const categoryIds = new Set()
  const includeCategory = id => {
    categoryIds.add(id)
    state.categories.filter(item => item.parentId === id).forEach(item => includeCategory(item.id))
  }
  if (activeCategory) includeCategory(activeCategory)
  const documents = activeCategory ? state.documents.filter(item => item.categoryId && categoryIds.has(item.categoryId)) : state.documents
  content.innerHTML = `<div class="knowledge-layout">
    <aside class="category-panel">
      <div class="panel-heading"><div><b>知识目录</b><small>可自定义层级</small></div><button id="add-category" class="button small">+ 目录</button></div>
      <button class="all-category ${activeCategory === '' ? 'active' : ''}" id="all-category">全部文档 <span>${state.documents.length}</span></button>
      <div class="category-tree">${categoryTree() || '<p class="muted category-empty">还没有目录</p>'}</div>
    </aside>
    <section class="document-panel">
      <div class="section-heading"><div><h2>${escapeHtml(state.categories.find(item => item.id === activeCategory)?.name || '全部文档')}</h2><p>${activeCategory ? '包含当前目录及所有子目录中的文档' : '按文档用途分别建立模板目录索引和正文分块索引'}</p></div><span class="record-count">${documents.length} 份文档</span></div>
      ${documents.length ? `<table class="data-table"><thead><tr><th>文档</th><th>用途 / 模板属性</th><th>状态</th><th>索引</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${documents.map(item => `<tr class="document-row" data-id="${item.id}">
        <td><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.originalName)}</small></td>
        <td><span class="tag">${escapeHtml(item.purposeName || purposeLabel(item.purposeId))}</span>${item.isGenerationTemplate ? `<small>${escapeHtml(item.templateFamily)} · ${escapeHtml(item.templateVariant || '默认')} · ${escapeHtml(item.version || '无版本')}</small>` : `<small>${escapeHtml(item.documentType || '未分类文档')}</small>`}</td>
        <td><span class="tag ${item.status}">${statusLabel(item.status)}</span></td>
        <td>${indexSummary(item)}</td>
        <td>${formatDate(item.updatedAt)}</td><td><button class="button small view-document" data-id="${item.id}">查看</button></td></tr>`).join('')}</tbody></table>` : '<div class="empty">这个目录还没有文档</div>'}
    </section>
  </div>`
  $('#add-category').onclick = () => openCategoryEditor()
  $('#all-category').onclick = () => { activeCategory = ''; renderKnowledge() }
  $$('.category-select').forEach(button => button.onclick = () => { activeCategory = button.dataset.id; renderKnowledge() })
  $$('.category-toggle:not(:disabled)').forEach(button => button.onclick = () => {
    if (collapsedCategories.has(button.dataset.id)) collapsedCategories.delete(button.dataset.id)
    else collapsedCategories.add(button.dataset.id)
    renderKnowledge()
  })
  $$('.category-edit').forEach(button => button.onclick = () => openCategoryEditor(state.categories.find(item => item.id === button.dataset.id)))
  $$('.view-document').forEach(button => button.onclick = () => openDocument(state.documents.find(item => item.id === button.dataset.id)))
}

function openSkillEditor(skill) {
  const current = skill || { name: '', description: '', instructions: '', enabled: true, resources: [] }
  const pendingResources = new Map()
  const removedResources = new Set()
  const resourceKinds = {
    scripts: { title: '脚本', description: 'Python、Shell 等辅助程序文件，当前只保存不自动执行', action: '添加脚本' },
    references: { title: '参考资料', description: '规则、说明、接口文档和专业资料', action: '添加资料' },
    assets: { title: '模板与素材', description: 'Word、Excel、图片等输出时使用的文件', action: '添加素材' },
  }
  openDialog(skill ? '编辑技能' : '新建技能', '只写特殊任务的专业方法；流程要求和知识内容仍分别维护在业务流程与知识库中。', `
    <div class="skill-form">
      <section class="skill-section">
        <div class="skill-section-heading"><span>1</span><div><b>基本信息</b><small>用于识别技能并判断何时调用</small></div></div>
        <div class="form-grid skill-basics-grid">
          <div class="field"><label>技能名称（英文）</label><input id="skill-name" value="${escapeHtml(current.name)}" placeholder="例如：contract-risk-review" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxlength="64" required><small>英文小写、数字和短横线，同时作为目录名和 frontmatter name。</small></div>
          <div class="field"><label>简短说明</label><input id="skill-description" value="${escapeHtml(current.description)}" placeholder="说明技能做什么、何时使用以及主要输出" maxlength="500" required><small>Harness 会根据这段说明判断是否调用该技能。</small></div>
        </div>
      </section>
      <section class="skill-section">
        <div class="skill-section-heading"><span>2</span><div><b>执行规则</b><small>保存为 SKILL.md 正文，支持 Markdown</small></div><code>SKILL.md</code></div>
        <textarea id="skill-instructions" class="skill-instructions" aria-label="执行规则" placeholder="## 操作步骤&#10;1. 确认用户需求&#10;2. 执行专业检查&#10;3. 按要求输出结果" required>${escapeHtml(current.instructions)}</textarea>
      </section>
      <section class="skill-section">
        <div class="skill-section-heading"><span>3</span><div><b>相关资源</b><small>AI 创建和人工上传的文件统一保存在技能目录中</small></div><code>可选</code></div>
        <div class="skill-resource-grid">${Object.entries(resourceKinds).map(([kind, definition]) => `
          <article class="skill-resource-card" data-resource-kind="${kind}">
            <header><div><b>${definition.title}</b><small>${definition.description}</small></div><label class="button small resource-picker" for="skill-resource-${kind}">${definition.action}<input id="skill-resource-${kind}" type="file" multiple data-resource-input="${kind}"></label></header>
            <div class="skill-resource-list" data-resource-list="${kind}"></div>
          </article>`).join('')}</div>
        <p class="skill-resource-note">在 SKILL.md 中使用相对路径引用资源，例如 <code>scripts/review.py</code> 或 <code>assets/template.docx</code>。页面选择的文件会在保存技能时上传。</p>
      </section>
      <label class="skill-toggle"><div><b>允许部门助手使用</b><span>关闭后保留 Skill 文件，但不会出现在模型和用户的可调用列表中。</span></div><input id="skill-enabled" type="checkbox" ${current.enabled ? 'checked' : ''}><i aria-hidden="true"></i></label>
    </div>`, async () => {
      const result = await api('skill/save', {
        id: skill?.id,
        name: $('#skill-name').value.trim(),
        description: $('#skill-description').value.trim(),
        instructions: $('#skill-instructions').value.trim(),
        enabled: $('#skill-enabled').checked,
      })
      const skillId = result.skill.id
      for (const path of removedResources) await api('skill/resource-delete', { skillId, path })
      for (const [path, file] of pendingResources) {
        await api('skill/resource-save', { skillId, path, contentBase64: bufferToBase64(await file.arrayBuffer()) })
      }
    }, { wide: true, kind: 'skill', successMessage: skill ? '技能已更新' : '技能已创建' })

  const renderResources = () => {
    for (const kind of Object.keys(resourceKinds)) {
      const list = $(`[data-resource-list="${kind}"]`, dialog)
      const existing = (current.resources || []).filter(resource => resource.kind === kind && !removedResources.has(resource.path) && !pendingResources.has(resource.path))
      const pending = [...pendingResources].filter(([path]) => path.startsWith(`${kind}/`))
      list.innerHTML = [
        ...existing.map(resource => `<div class="skill-resource-row"><a href="${resourceUrl(skill?.id || current.name, resource.path)}" download>${escapeHtml(resource.path)}</a><span>${formatBytes(resource.size)}</span><button type="button" class="icon-button resource-remove" data-resource-path="${escapeHtml(resource.path)}" aria-label="删除 ${escapeHtml(resource.name)}">×</button></div>`),
        ...pending.map(([path, file]) => `<div class="skill-resource-row pending"><span>${escapeHtml(path)}</span><em>待上传 · ${formatBytes(file.size)}</em><button type="button" class="icon-button resource-remove" data-resource-path="${escapeHtml(path)}" aria-label="取消上传 ${escapeHtml(file.name)}">×</button></div>`),
      ].join('') || '<p class="skill-resource-empty">暂无文件</p>'
    }
    $$('.resource-remove', dialog).forEach(button => button.onclick = () => {
      const path = button.dataset.resourcePath
      if (pendingResources.has(path)) pendingResources.delete(path)
      else removedResources.add(path)
      renderResources()
    })
  }
  $$('[data-resource-input]', dialog).forEach(input => input.onchange = () => {
    const kind = input.dataset.resourceInput
    for (const file of input.files || []) {
      if (file.name.startsWith('.')) { toast('不能上传隐藏文件', true); continue }
      const path = `${kind}/${file.name}`
      pendingResources.set(path, file)
      removedResources.delete(path)
    }
    input.value = ''
    renderResources()
  })
  renderResources()
}

function skillResourceSummary(skill) {
  const labels = { scripts: '脚本', references: '参考资料', assets: '素材' }
  const parts = Object.entries(labels).filter(([kind]) => skill.resourceCounts?.[kind]).map(([kind, label]) => `${skill.resourceCounts[kind]} 个${label}`)
  return parts.length ? parts.join(' · ') : '暂无附加资源'
}

function renderSkills() {
  setAction('+ 新建技能', () => openSkillEditor())
  content.innerHTML = state.skills.length ? `<div class="process-list skills-grid">${state.skills.map(skill => `
    <article class="item-card skill-card">
      <div class="item-head"><div><div class="title-line"><h3>${escapeHtml(skill.name)}</h3><span class="tag ${skill.valid === false ? 'obsolete' : skill.enabled ? 'high' : 'obsolete'}">${skill.valid === false ? '待修复' : skill.enabled ? '已启用' : '已停用'}</span></div><p>${escapeHtml(skill.error || skill.description)}</p></div>
        <div class="actions"><button class="button small edit-skill" data-id="${skill.id}">编辑</button><button class="button small danger delete-skill" data-id="${skill.id}">删除</button></div></div>
      <div class="meta"><span>${skillResourceSummary(skill)}</span><span>更新于 ${formatDate(skill.updatedAt)}</span></div>
    </article>`).join('')}</div>` : `<div class="empty"><b>还没有特殊技能</b><p>常规任务仍按业务流程和知识库处理；只有需要固定专业方法时才创建技能。</p></div>`
  $$('.edit-skill').forEach(button => button.onclick = () => openSkillEditor(state.skills.find(item => item.id === button.dataset.id)))
  $$('.delete-skill').forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个技能吗？', '对应的 SKILL.md 文件会一并删除。')) return
    try { await api('skill/delete', { id: button.dataset.id }); await refresh(); renderPage(); toast('技能已删除') } catch (error) { toast(error.message, true) }
  })
}

function renderAssistant() {
  setAction('', null)
  if (!assistantHost.firstElementChild) assistantHost.innerHTML = `<div class="assistant-page"><iframe class="assistant-frame" src="${escapeHtml(state.services.harnessUrl)}" title="DeepSeek Harness AI 助手"></iframe></div>`
}

function principleRow(value = '', index = 0) {
  return `<div class="principle-row"><span class="principle-number">${index + 1}</span><textarea class="principle-text" rows="2" required>${escapeHtml(value)}</textarea><div class="actions"><button type="button" class="button small principle-up" aria-label="上移">↑</button><button type="button" class="button small principle-down" aria-label="下移">↓</button><button type="button" class="button small danger principle-remove">删除</button></div></div>`
}

function renumberPrinciples() {
  $$('.principle-row').forEach((row, index) => $('.principle-number', row).textContent = index + 1)
}

function settingsPayload(overrides = {}) {
  return {
    assistant: state.settings.assistant,
    chunking: state.settings.chunking,
    retrieval: state.settings.retrieval,
    embeddingModel: state.settings.embeddingModel,
    rerankModel: state.settings.rerankModel,
    ...overrides,
  }
}

function bindPrincipleEditor() {
  $('#add-principle').onclick = () => { $('#principles-editor').insertAdjacentHTML('beforeend', principleRow('', $$('.principle-row').length)); renumberPrinciples() }
  $('#principles-editor').onclick = event => {
    const row = event.target.closest('.principle-row')
    if (!row) return
    if (event.target.closest('.principle-remove')) row.remove()
    if (event.target.closest('.principle-up') && row.previousElementSibling) row.parentElement.insertBefore(row, row.previousElementSibling)
    if (event.target.closest('.principle-down') && row.nextElementSibling) row.parentElement.insertBefore(row.nextElementSibling, row)
    renumberPrinciples()
  }
}

function openAssistantSettings() {
  const assistant = state.settings.assistant
  openDialog('部门助手规则', '配置角色、工作原则和默认交互方式；新任务会通过 MCP 读取最新规则。', `
    <div class="settings-dialog-form">
      <div class="field"><label>角色定位</label><textarea id="assistant-role" required>${escapeHtml(assistant.role)}</textarea></div>
      <div class="field"><div class="field-heading"><label>工作原则</label><button type="button" id="add-principle" class="button small">+ 添加原则</button></div><div id="principles-editor" class="principles-editor">${assistant.principles.map(principleRow).join('')}</div></div>
      <div class="form-grid compact-form-grid">
        <div class="field"><label>默认语言</label><select id="assistant-language"><option value="zh-CN" ${assistant.defaultLanguage === 'zh-CN' ? 'selected' : ''}>中文</option><option value="en" ${assistant.defaultLanguage === 'en' ? 'selected' : ''}>英文</option></select></div>
        <div class="assistant-defaults"><label class="check-field"><input id="assistant-draft" type="checkbox" ${assistant.draftByDefault ? 'checked' : ''}> 生成内容默认视为草稿</label><label class="check-field"><input id="assistant-ask" type="checkbox" ${assistant.askWhenMissing ? 'checked' : ''}> 关键信息缺失时先询问</label></div>
      </div>
    </div>`, async () => {
      await api('settings/save', settingsPayload({ assistant: {
        role: $('#assistant-role').value.trim(),
        principles: $$('.principle-text', dialogContent).map(node => node.value.trim()).filter(Boolean),
        defaultLanguage: $('#assistant-language').value,
        draftByDefault: $('#assistant-draft').checked,
        askWhenMissing: $('#assistant-ask').checked,
      } }))
    }, { wide: true, successMessage: '部门助手规则已保存' })
  bindPrincipleEditor()
}

function openChunkingSettings() {
  openDialog('默认分块设置', '作为文档用途和单个文档未覆盖规则时的系统默认值。', `
    <div class="settings-dialog-form"><div class="settings-dialog-note">上传文档时仍可以按用途或单个文件覆盖此设置。</div>${chunkSettingsForm(state.settings.chunking)}</div>`, async () => {
      await api('settings/save', settingsPayload({ chunking: collectChunkSettings() }))
    }, { wide: true, successMessage: '默认分块设置已保存' })
  toggleChunkFields()
  $('#chunk-mode').onchange = toggleChunkFields
}

function openRetrievalSettings() {
  const retrieval = state.settings.retrieval
  openDialog('检索与推荐', '配置向量初召回、重排序和最终推荐数量。', `
    <div class="form-grid settings-dialog-form compact-form-grid">
      <div class="field"><label>向量召回数量</label><input id="vector-recall" type="number" min="1" max="100" value="${retrieval.vectorRecall}"></div>
      <div class="field"><label>Rerank 保留数量</label><input id="rerank-top" type="number" min="1" max="50" value="${retrieval.rerankTopN}"></div>
      <div class="field"><label>模板推荐数量</label><input id="recommend-count" type="number" min="1" max="10" value="${retrieval.recommendCount}"></div>
      <div class="field"><label>Score 阈值</label><input id="score-threshold" type="number" min="0" max="1" step="0.05" value="${retrieval.scoreThreshold ?? 0.5}"></div>
      <label class="check-field full"><input id="threshold-enabled" type="checkbox" ${retrieval.scoreThreshold === null ? '' : 'checked'}> 启用 Score 阈值</label>
      <p class="muted small-copy full">知识量较少时建议关闭阈值，先由 Rerank 和推荐数量筛选结果。</p>
    </div>`, async () => {
      await api('settings/save', settingsPayload({ retrieval: {
        vectorRecall: Number($('#vector-recall').value),
        rerankTopN: Number($('#rerank-top').value),
        recommendCount: Number($('#recommend-count').value),
        scoreThreshold: $('#threshold-enabled').checked ? Number($('#score-threshold').value) : null,
      } }))
    }, { successMessage: '检索与推荐设置已保存' })
}

function openModelSettings() {
  const settings = state.settings
  openDialog('模型与服务', '查看当前模型配置和基础服务连接状态。', `
    <div class="settings-dialog-form"><div class="form-grid compact-form-grid">
      <div class="field full"><label>Embedding 模型</label><input value="${escapeHtml(settings.embeddingModel)}" readonly></div>
      <div class="field full"><label>Rerank 模型</label><input value="${escapeHtml(settings.rerankModel)}" readonly></div>
    </div><div class="service-list">${serviceBadge(state.services.database, 'PostgreSQL / pgvector')}${serviceBadge(state.services.docling, 'Docling Serve')}${serviceBadge(state.services.siliconflow, 'Embedding / Rerank 已配置')}${serviceBadge(state.services.metadata, 'AI 元数据分析已配置')}${serviceBadge(state.services.harness, 'DeepSeek Harness')}</div><p class="muted small-copy">模型名称暂时只读，避免更换模型后旧向量失效。增加批量重建索引能力后再开放切换。</p></div>`, async () => {}, { readOnly: true })
}

function settingRow({ icon, title, description, summary, action, actionLabel, tone = '' }) {
  return `<article class="settings-row ${tone}">
    <span class="settings-row-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span>
    <div class="settings-row-body"><h3>${title}</h3><p>${description}</p><span class="settings-row-summary">${summary}</span></div>
    <button type="button" class="button settings-row-action" data-settings-action="${action}">${actionLabel}</button>
  </article>`
}

function renderSettings() {
  const settings = state.settings
  setAction('', null)
  const onlineServices = ['database', 'docling', 'siliconflow', 'metadata', 'harness'].filter(key => state.services[key]).length
  const icons = {
    chunking: '<path d="M4 6h16M4 12h10M4 18h16"/><path d="m17 10 3 2-3 2"/>',
    retrieval: '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5M7 10h6M10 7v6"/>',
    purposes: '<path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5M8 12h8M8 16h6"/>',
    assistant: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18.5 16.5 20 20l3.5 1.5L20 23l-1.5 3.5L17 23l-3.5-1.5L17 20z" transform="translate(-2 -2) scale(.9)"/>',
    models: '<path d="M8 3h8v4H8zM5 9h14v10H5z"/><path d="M9 13h.01M15 13h.01M9 16h6M3 12h2M19 12h2"/>',
  }
  content.innerHTML = `<div class="settings-workspace">
    <section class="settings-section settings-section-main">
      <header><div><h2>知识与检索</h2><p>管理文档如何入库、召回和推荐</p></div><span class="settings-section-count">3 项</span></header>
      <div class="settings-list">
        ${settingRow({ icon: icons.chunking, title: '默认分块设置', description: '用途未单独指定时采用的正文切块规则', summary: escapeHtml(chunkSettingsSummary(settings.chunking)), action: 'chunking', actionLabel: '配置分块' })}
        ${settingRow({ icon: icons.retrieval, title: '检索与推荐', description: '向量召回、Rerank 和模板推荐数量', summary: `召回 ${settings.retrieval.vectorRecall} · Rerank ${settings.retrieval.rerankTopN} · 推荐 ${settings.retrieval.recommendCount}`, action: 'retrieval', actionLabel: '配置检索' })}
        ${settingRow({ icon: icons.purposes, title: '文档用途', description: '定义文档能否作为模板及是否建立正文索引', summary: `${state.purposes.length} 种用途 · ${state.documents.length} 份文档`, action: 'purposes', actionLabel: '管理用途' })}
      </div>
    </section>
    <div class="settings-secondary">
      <section class="settings-section">
        <header><div><h2>助手行为</h2><p>控制部门助手的默认工作方式</p></div></header>
        <div class="settings-list">${settingRow({ icon: icons.assistant, title: '部门助手规则', description: '角色定位、工作原则和默认交互方式', summary: `${settings.assistant.principles.length} 条原则 · ${settings.assistant.defaultLanguage === 'zh-CN' ? '中文' : '英文'}`, action: 'assistant', actionLabel: '配置规则' })}</div>
      </section>
      <section class="settings-section">
        <header><div><h2>模型与服务</h2><p>确认知识处理和对话服务状态</p></div><span class="service-health ${onlineServices === 5 ? 'ok' : 'off'}"><i></i>${onlineServices}/5 正常</span></header>
        <div class="settings-list">${settingRow({ icon: icons.models, title: '模型与服务', description: '查看嵌入、重排模型和基础服务连接', summary: onlineServices === 5 ? '全部基础服务可用' : `${5 - onlineServices} 项服务需要检查`, action: 'models', actionLabel: '查看状态', tone: onlineServices === 5 ? 'service-ok' : 'service-off' })}</div>
      </section>
    </div>
  </div>`
  const actions = { assistant: openAssistantSettings, chunking: openChunkingSettings, retrieval: openRetrievalSettings, models: openModelSettings, purposes: openPurposeManager }
  $$('.settings-row-action').forEach(button => button.onclick = actions[button.dataset.settingsAction])
}

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
  const renderers = { dashboard: renderDashboard, processes: renderProcesses, knowledge: renderKnowledge, skills: renderSkills, assistant: renderAssistant, settings: renderSettings }
  ;(renderers[page] || renderDashboard)()
  $('main').scrollTop = 0
}

async function start() {
  content.innerHTML = '<div class="loading">正在连接部门数据库和知识服务…</div>'
  try { await refresh(); renderPage() } catch (error) { content.innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}</div>` }
}

window.addEventListener('hashchange', renderPage)
start()
