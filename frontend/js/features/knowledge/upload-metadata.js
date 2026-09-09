import { $, escapeHtml } from '../../core/dom.js'
import { renderIndexPlan } from './upload-chunks.js'
import { categoryOptions, createCategory } from './categories.js'

export function inlineCategoryCreatorHtml(prefix = 'upload') {
  return {
    trigger: `<button type="button" class="button small" id="${prefix}-category-create" aria-expanded="false" aria-controls="${prefix}-category-creator">+ 新建目录</button>`,
    panel: `<div id="${prefix}-category-creator" class="inline-category-creator" hidden>
      <div class="field"><label for="${prefix}-category-name">新目录名称</label><input id="${prefix}-category-name"></div>
      <div class="field"><label for="${prefix}-category-parent">上级目录</label><select id="${prefix}-category-parent"><option value="">根目录</option></select></div>
      <div class="actions"><button type="button" class="button" id="${prefix}-category-save">创建目录</button><button type="button" class="button" id="${prefix}-category-cancel">取消创建</button></div>
      <p id="${prefix}-category-error" class="field-error" role="alert" hidden></p>
    </div>`,
  }
}

export function metadataFormHtml({ documentId, categoryOptionsHtml, purposes }) {
  const creator = inlineCategoryCreatorHtml()
  return `<div class="form-grid">
    <div class="field"><label>文档 ID</label><input id="document-id" value="${escapeHtml(documentId)}" placeholder="purchase-contract-v2" pattern="[a-z0-9][a-z0-9-]{0,63}" required></div>
    <div class="field"><label>文档标题</label><input id="document-title" required></div>
    <div class="field"><label>文档用途</label><select id="document-purpose"><option value="" selected>待确认</option>${purposes.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('')}</select></div>
    <div class="field"><label>文档类型</label><input id="document-type" placeholder="设计方案 / 补充协议"></div>
    <div class="field"><label>知识目录</label><select id="document-category"><option value="">未分类</option>${categoryOptionsHtml}</select>${creator.trigger}</div>
    <div class="field"><label>状态</label><select id="document-status"><option value="effective">有效</option><option value="draft">草稿</option><option value="obsolete">已废止</option></select></div>
    <div class="field full"><label>关键词</label><input id="document-keywords" placeholder="CPU、服务器、采购、补充协议"></div>
    <div class="field full"><label>文档简介</label><textarea id="document-summary" placeholder="说明文档内容和适用范围"></textarea></div>
  </div>
  ${creator.panel}
  <div id="template-fields" hidden><div class="form-grid inset">
    <div class="field"><label>模板家族</label><input id="template-family" placeholder="高性能网络组网方案"></div>
    <div class="field"><label>模板变体</label><input id="template-variant" placeholder="RoCE / InfiniBand"></div>
    <div class="field"><label>版本</label><input id="template-version" value="V1.0" placeholder="V1.0"></div>
  </div></div>
  <div class="form-grid inset"><div class="field full"><label>适用场景（AI建议，可修改）</label><input id="template-scenario" placeholder="GPU 集群网络"></div></div>
  <div class="index-plan" id="index-plan"></div>`
}

export function bindInlineCategoryCreator(onCreated, { isCurrent = () => true, run = operation => operation(), prefix = 'upload', categorySelect = $('#document-category') } = {}) {
  const panel = $(`#${prefix}-category-creator`)
  const trigger = $(`#${prefix}-category-create`)
  const name = $(`#${prefix}-category-name`)
  const parent = $(`#${prefix}-category-parent`)
  const save = $(`#${prefix}-category-save`)
  const cancel = $(`#${prefix}-category-cancel`)
  const errorNode = $(`#${prefix}-category-error`)
  const canUpdate = () => panel.isConnected && panel.closest('dialog')?.open
    && !panel.closest('dialog').classList.contains('is-closing') && isCurrent()
  const clearNameError = () => {
    name.removeAttribute('aria-invalid')
    name.removeAttribute('aria-describedby')
    errorNode.hidden = true
  }
  name.addEventListener('input', () => { if (name.value.trim()) clearNameError() })
  const close = (restoreFocus = true) => {
    panel.hidden = true
    trigger.setAttribute('aria-expanded', 'false')
    if (restoreFocus) categorySelect.focus()
  }
  trigger.onclick = () => {
    panel.hidden = false
    trigger.setAttribute('aria-expanded', 'true')
    parent.innerHTML = `<option value="">根目录</option>${categoryOptions(categorySelect.value)}`
    name.focus()
  }
  cancel.onclick = close
  save.onclick = async () => {
    if (save.disabled || !canUpdate()) return
    errorNode.hidden = true
    if (!name.value.trim()) {
      errorNode.textContent = '请填写新目录名称'
      errorNode.hidden = false
      name.setAttribute('aria-invalid', 'true')
      name.setAttribute('aria-describedby', errorNode.id)
      name.focus()
      return
    }
    clearNameError()
    let created = false
    await run(async () => {
      const controls = [save, cancel, trigger, name, parent]
      controls.forEach(control => { control.disabled = true })
      save.setAttribute('aria-busy', 'true')
      try {
        const category = await createCategory({ name: name.value.trim(), parentId: parent.value || null })
        if (!canUpdate()) return
        categorySelect.innerHTML = `<option value="">未分类</option>${categoryOptions(category.id)}`
        categorySelect.value = category.id
        onCreated(category)
        clearNameError()
        name.value = ''
        created = true
        close(false)
      } catch (error) {
        if (!canUpdate()) return
        errorNode.textContent = `创建失败：${error.message}。请重试。`
        errorNode.hidden = false
      } finally {
        if (canUpdate()) {
          controls.forEach(control => { control.disabled = false })
          save.removeAttribute('aria-busy')
        }
      }
    })
    if (created && canUpdate()) categorySelect.focus()
  }
}

export function selectedPurpose(purposes) {
  return purposes.find(item => item.id === $('#document-purpose')?.value)
}

export function togglePurposeFields(purposes) {
  const purpose = selectedPurpose(purposes)
  $('#template-fields').hidden = !purpose?.canGenerateTemplate
  $('#chunk-fields').hidden = !purpose?.chunkBody
  $('#template-family').required = Boolean(purpose?.canGenerateTemplate)
  $('#preview-button').textContent = purpose?.chunkBody ? '解析、分析并预览分块' : '解析并自动分析'
  renderIndexPlan(purpose)
  return purpose
}

export function applyMetadataSuggestion(metadata, purposes) {
  if (!metadata) return
  const setIfPresent = (selector, value) => {
    if (!value) return
    const control = $(selector)
    control.value = value
    control.dataset.aiSuggested = 'true'
  }
  setIfPresent('#document-title', metadata.title)
  setIfPresent('#document-type', metadata.documentType)
  setIfPresent('#document-summary', metadata.summary)
  setIfPresent('#document-keywords', (metadata.keywords || []).join('、'))
  setIfPresent('#template-family', metadata.templateFamily)
  setIfPresent('#template-variant', metadata.templateVariant)
  setIfPresent('#template-version', metadata.version)
  setIfPresent('#template-scenario', metadata.applicableScenario)
  const suggestedPurpose = purposes.find(item => item.id === metadata.suggestedPurposeId)
  if (suggestedPurpose) {
    const control = $('#document-purpose')
    control.value = suggestedPurpose.id
    control.dataset.aiSuggested = 'true'
  }
  togglePurposeFields(purposes)
}

export function collectMetadata(outline) {
  return {
    id: $('#document-id').value.trim(),
    title: $('#document-title').value.trim(),
    purposeId: $('#document-purpose').value,
    documentType: $('#document-type').value.trim(),
    keywords: $('#document-keywords').value.split(/[、,，\n]+/).map(item => item.trim()).filter(Boolean),
    outline,
    categoryId: $('#document-category').value,
    status: $('#document-status').value,
    summary: $('#document-summary').value.trim(),
    templateFamily: $('#template-family').value.trim(),
    templateVariant: $('#template-variant').value.trim(),
    version: $('#template-version').value.trim(),
    applicableScenario: $('#template-scenario').value.trim(),
  }
}

export function validateMetadata(purposes) {
  const purpose = selectedPurpose(purposes)
  const required = [$('#document-title'), $('#document-purpose')]
  if (purpose?.canGenerateTemplate) required.push($('#template-family'))
  return required.find(control => !control.value.trim())
}
