import { $, escapeHtml } from '../../core/dom.js'
import { applyScope, collectScope, scopeFieldsHtml, validateScope } from './scope.js'
import { renderIndexPlan } from './upload-chunks.js'

export function metadataFormHtml({ documentId, categoryOptionsHtml, purposes, processes }) {
  return `<div class="form-grid">
    <div class="field"><label>文档 ID</label><input id="document-id" value="${escapeHtml(documentId)}" placeholder="purchase-contract-v2" pattern="[a-z0-9][a-z0-9-]{0,63}" required></div>
    <div class="field"><label>文档标题</label><input id="document-title" required></div>
    <div class="field"><label>文档用途</label><select id="document-purpose"><option value="" selected>待确认</option>${purposes.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('')}</select></div>
    <div class="field"><label>文档类型</label><input id="document-type" placeholder="设计方案 / 补充协议"></div>
    <div class="field"><label>知识目录</label><select id="document-category"><option value="">未分类</option>${categoryOptionsHtml}</select></div>
    <div class="field"><label>状态</label><select id="document-status"><option value="effective">有效</option><option value="draft">草稿</option><option value="obsolete">已废止</option></select></div>
    <div class="field full"><label>关键词</label><input id="document-keywords" placeholder="CPU、服务器、采购、补充协议"></div>
    <div class="field full"><label>文档简介</label><textarea id="document-summary" placeholder="说明文档内容和适用范围"></textarea></div>
  </div>
  <div id="template-fields" hidden><div class="form-grid inset">
    <div class="field"><label>模板家族</label><input id="template-family" placeholder="高性能网络组网方案"></div>
    <div class="field"><label>模板变体</label><input id="template-variant" placeholder="RoCE / InfiniBand"></div>
    <div class="field"><label>版本</label><input id="template-version" value="V1.0" placeholder="V1.0"></div>
  </div></div>
  ${scopeFieldsHtml('upload', processes, { scopeType: '' })}
  <div class="index-plan" id="index-plan"></div>`
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

export function applyMetadataSuggestion(metadata, purposes, processes) {
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
  applyScope('upload', metadata, processes)
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
    ...collectScope('upload'),
  }
}

export function validateMetadata(purposes) {
  const purpose = selectedPurpose(purposes)
  const required = [$('#document-title'), $('#document-purpose')]
  if (purpose?.canGenerateTemplate) required.push($('#template-family'))
  return required.find(control => !control.value.trim()) || validateScope('upload')
}
