import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { openDialog } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'
import { activeCategory, categoryOptions } from './categories.js'
import { chunkSettingsForm, collectChunkSettings, setChunkSettings, toggleChunkFields } from './purposes.js'

async function refreshUpload(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

function previewKnowledge(body) { return request('/api/knowledge/preview', { method: 'POST', body }) }
function rechunkKnowledge(previewId, chunkSettings) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/rechunk`, { method: 'POST', body: chunkSettings }) }
function indexKnowledge(body) {
  const path = `/api/knowledge/previews/${encodeURIComponent(body.previewId)}/index`
  const payload = { ...body }
  delete payload.previewId
  return request(path, { method: 'POST', body: payload })
}
function deleteKnowledgePreview(previewId) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}`, { method: 'DELETE' }) }

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

export function openKnowledgeUpload(renderPage) {
  const chunking = state.settings.chunking
  const defaultPurpose = state.purposes.find(item => item.id === 'reference-knowledge') || state.purposes[0]
  let preview = null
  const discardPreview = async () => {
    if (!preview) return
    const previewId = preview.id
    preview = null
    try { await deleteKnowledgePreview(previewId) } catch (_) {}
  }
  const currentDialog = openDialog('知识入库', '解析正文 → AI建议元数据 → 人工确认 → 按用途建立索引', `
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
      await indexKnowledge({
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
    }, { wide: true, saveLabel: '确认并建立索引', successMessage: '文档已入库并按用途完成索引', afterSave: () => refreshUpload(renderPage) })
  currentDialog.element.addEventListener('close', () => { void discardPreview() }, { once: true })
  currentDialog.saveButton.disabled = true
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
      preview = await previewKnowledge({ fileName: file.name, mimeType: file.type, fileBase64: await fileToBase64(file), chunkSettings: collectChunkSettings() })
      applyMetadataSuggestion(preview.metadata)
      renderChunkPreview(preview.chunks)
      $('#preview-summary').textContent = `${preview.fileName} · ${preview.characters.toLocaleString()} 字符 · ${preview.chunks.length} 块`
      const suggestedPurpose = state.purposes.find(item => item.id === preview.metadata?.suggestedPurposeId)
      $('#metadata-status').textContent = preview.metadataError
        ? `正文解析成功，但AI元数据建议失败：${preview.metadataError}。可以手工填写后保存。`
        : `AI建议已填入${suggestedPurpose ? `，建议用途为“${suggestedPurpose.name}”` : ''}。用途以您上传前的选择为准，请确认其他属性。`
      $('#rechunk-button').hidden = false
      currentDialog.saveButton.disabled = false
    } catch (error) { toast(error.message, true) } finally { button.disabled = false; toggleDocumentPurpose() }
  }
  $('#rechunk-button').onclick = async () => {
    if (!preview) return
    try {
      preview = await rechunkKnowledge(preview.id, collectChunkSettings())
      renderChunkPreview(preview.chunks)
      $('#preview-summary').textContent = `${preview.characters.toLocaleString()} 字符 · ${preview.chunks.length} 块`
    } catch (error) { toast(error.message, true) }
  }
}
