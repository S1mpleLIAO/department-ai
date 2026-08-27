import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { openDialog } from '../../ui/dialog.js'
import { activeCategory, categoryOptions } from './categories.js'
import {
  applyMetadataSuggestion,
  collectMetadata,
  metadataFormHtml,
  selectedPurpose,
  togglePurposeFields,
  validateMetadata,
} from './upload-metadata.js'
import {
  chunkPanelHtml,
  collectChunkSettings,
  collectPreviewChunks,
  hasEnabledChunk,
  renderChunkPreview,
  renderIndexPlan,
  setChunkSettings,
  toggleChunkFields,
} from './upload-chunks.js'

async function refreshUpload(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

function previewKnowledge(body) { return request('/api/knowledge/preview', { method: 'POST', body }) }
function analyzeKnowledge(previewId) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/analyze`, { method: 'POST' }) }
function rechunkKnowledge(previewId, settings) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/rechunk`, { method: 'POST', body: settings }) }
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

function purposeSettings(purpose) {
  return purpose?.inheritChunking ? state.settings.chunking : purpose?.chunkSettings || state.settings.chunking
}

export function openKnowledgeUpload(renderPage) {
  const workflow = {
    stage: 'selecting', preview: null, metadata: null, chunks: [],
    confirmedMetadata: null, indexPurposeId: '', saving: false,
  }
  const stages = ['selecting', 'reviewing-metadata', 'reviewing-index', 'confirming']
  const currentDialog = openDialog('知识入库', '解析正文 → 确认属性 → 预览索引 → 最终入库', `
    <div class="upload-stepper" aria-label="知识入库步骤">
      <span data-upload-stage="selecting"><button type="button" data-upload-nav="selecting"><b>1</b>解析正文</button></span><i aria-hidden="true"></i>
      <span data-upload-stage="reviewing-metadata"><button type="button" data-upload-nav="reviewing-metadata"><b>2</b>确认属性</button></span><i aria-hidden="true"></i>
      <span data-upload-stage="reviewing-index"><button type="button" data-upload-nav="reviewing-index"><b>3</b>预览索引</button></span><i aria-hidden="true"></i>
      <span data-upload-stage="confirming"><button type="button" data-upload-nav="confirming"><b>4</b>最终入库</button></span>
    </div>
    <div class="upload-workflow">
      <section class="upload-column" data-upload-step="selecting" aria-labelledby="upload-selecting-title">
        <h3 id="upload-selecting-title" tabindex="-1">选择文件并解析正文</h3>
        <div class="field full"><label>选择文件</label><input id="knowledge-file" type="file" accept=".txt,.md,.csv,.json,.docx,.pdf,.pptx,.xlsx"></div>
        <p class="muted small-copy">支持 TXT、Markdown、CSV、JSON、Word、PDF、PowerPoint 和 Excel 文件。</p>
        <button type="button" class="button primary" id="parse-document">解析正文</button>
        <p id="parse-error" class="field-error" role="alert" hidden></p>
      </section>
      <section class="upload-column" data-upload-step="reviewing-metadata" aria-labelledby="upload-metadata-title" hidden>
        <h3 id="upload-metadata-title" tabindex="-1">确认文档属性</h3>
        <p id="parse-summary" class="muted small-copy"></p>
        ${metadataFormHtml({ documentId: `knowledge-${Date.now()}`, categoryOptionsHtml: categoryOptions(activeCategory), purposes: state.purposes })}
        <span id="preview-button" hidden></span>
        <div class="actions">
          <button type="button" class="button" id="analyze-metadata">使用 AI 分析</button>
          <button type="button" class="button primary" id="metadata-continue">确认属性并继续</button>
        </div>
        <p id="metadata-error" class="field-error" role="alert" hidden></p>
      </section>
      <section class="preview-column" data-upload-step="reviewing-index" aria-labelledby="upload-index-title" hidden>
        <h3 id="upload-index-title" tabindex="-1">设置并预览索引</h3>
        <div class="index-plan" id="review-index-plan"></div>
        ${chunkPanelHtml(state.settings.chunking)}
        <div class="preview-heading"><div><h3>分块预览</h3><p id="preview-summary">确认用途后生成索引预览</p></div><button type="button" class="button small" id="rechunk-button">重新切块</button></div>
        <div id="chunk-preview" class="chunk-preview"><div class="empty compact">尚未生成索引预览</div></div>
        <p id="index-error" class="field-error" role="alert" hidden></p>
        <div class="actions">
          <button type="button" class="button" id="back-to-metadata">返回修改属性</button>
          <button type="button" class="button primary" id="index-continue">确认索引并继续</button>
        </div>
      </section>
      <section class="upload-column" data-upload-step="confirming" aria-labelledby="upload-confirming-title" hidden>
        <h3 id="upload-confirming-title" tabindex="-1">最终确认并入库</h3>
        <div class="document-detail" id="final-summary"></div>
        <div class="actions">
          <button type="button" class="button" id="back-to-index">返回修改索引</button>
          <button type="button" class="button" id="back-to-confirmed-metadata">返回修改属性</button>
        </div>
      </section>
    </div>`, async () => {
    if (workflow.stage !== 'confirming' || !workflow.preview || !workflow.confirmedMetadata) {
      throw new Error('请先完成最终确认')
    }
    setStage('saving')
    try {
      await indexKnowledge({
        previewId: workflow.preview.id,
        ...workflow.confirmedMetadata,
        chunks: workflow.chunks,
      })
      workflow.preview = null
    } catch (error) {
      setStage('confirming')
      throw error
    }
  }, {
    wide: true,
    saveLabel: '确认入库',
    successMessage: '文档已入库并按用途完成索引',
    afterSave: () => refreshUpload(renderPage),
  })

  function setStage(stage) {
    workflow.stage = stage
    workflow.saving = stage === 'saving'
    const visibleStage = workflow.saving ? 'confirming' : stage
    const currentIndex = stages.indexOf(visibleStage)
    $$('[data-upload-step]').forEach(panel => { panel.hidden = panel.dataset.uploadStep !== visibleStage })
    $$('[data-upload-stage]').forEach(step => {
      const index = stages.indexOf(step.dataset.uploadStage)
      step.classList.toggle('current', index === currentIndex)
      step.classList.toggle('completed', index < currentIndex)
      const button = $('[data-upload-nav]', step)
      button.disabled = workflow.saving || index >= currentIndex
    })
    currentDialog.saveButton.hidden = visibleStage !== 'confirming'
    currentDialog.saveButton.disabled = workflow.saving
    currentDialog.saveButton.textContent = workflow.saving ? '正在入库…' : '确认入库'
    if (!workflow.saving) $(`[data-upload-step="${visibleStage}"] h3`)?.focus()
  }

  async function discardPreview() {
    const previewId = workflow.preview?.id
    workflow.preview = null
    if (!previewId) return
    try { await deleteKnowledgePreview(previewId) } catch (_) {}
  }

  function clearError(selector) {
    const target = $(selector)
    target.hidden = true
    target.textContent = ''
  }

  function showError(selector, message) {
    const target = $(selector)
    target.textContent = message
    target.hidden = false
  }

  function clearMetadataForm(file) {
    const values = {
      '#document-title': file?.name.replace(/\.[^.]+$/, '') || '',
      '#document-purpose': '', '#document-type': '', '#document-category': '', '#document-status': 'effective',
      '#document-keywords': '', '#document-summary': '', '#template-family': '', '#template-variant': '',
      '#template-version': 'V1.0', '#template-scenario': '',
    }
    Object.entries(values).forEach(([selector, value]) => {
      const control = $(selector)
      control.value = value
      control.removeAttribute('aria-invalid')
      delete control.dataset.aiSuggested
      control.closest('.field')?.querySelector('.field-error')?.remove()
    })
    workflow.metadata = null
    workflow.chunks = []
    workflow.confirmedMetadata = null
    workflow.indexPurposeId = ''
    $('#chunk-preview').innerHTML = '<div class="empty compact">尚未生成索引预览</div>'
    $('#preview-summary').textContent = '确认用途后生成索引预览'
    $('#final-summary').innerHTML = ''
    clearError('#parse-error')
    clearError('#metadata-error')
    clearError('#index-error')
    setChunkSettings(state.settings.chunking)
    togglePurposeFields(state.purposes)
  }

  function invalidateIndex() {
    workflow.chunks = []
    workflow.indexPurposeId = ''
    $('#chunk-preview').innerHTML = '<div class="empty compact">用途已修改，请重新生成索引预览</div>'
    $('#preview-summary').textContent = '用途已变化，旧预览已失效'
    $('#index-continue').disabled = true
  }

  function renderReviewIndex(purpose) {
    $('#review-index-plan').innerHTML = renderIndexPlan(purpose)
    $('#rechunk-button').hidden = !purpose.chunkBody
    $('#index-continue').disabled = false
    if (!purpose.chunkBody) {
      $('#chunk-preview').innerHTML = '<div class="empty compact">此用途不建立正文分块，完整正文仍会保存</div>'
      $('#preview-summary').textContent = '整份模板索引 · 无正文分块'
    }
  }

  function renderFinalSummary(purpose) {
    const metadata = workflow.confirmedMetadata
    const category = state.categories.find(item => item.id === metadata.categoryId)
    const enabledChunks = workflow.chunks.filter(chunk => chunk.enabled).length
    $('#final-summary').innerHTML = `<div class="index-plan">
      <b>${escapeHtml(metadata.title)}</b>
      <span>文件：${escapeHtml(workflow.preview.fileName)}</span>
      <span>用途：${escapeHtml(purpose.name)}</span>
      <span>知识目录：${escapeHtml(category?.name || '未分类')}</span>
      <span>状态：${metadata.status === 'effective' ? '有效' : metadata.status === 'draft' ? '草稿' : '已废止'}</span>
      ${purpose.canGenerateTemplate ? `<span>模板家族：${escapeHtml(metadata.templateFamily)}</span>` : ''}
      <span>${purpose.chunkBody ? `有效分块：${enabledChunks} 块` : '正文不切块'}</span>
    </div>`
  }

  currentDialog.element.addEventListener('close', () => { void discardPreview() }, { once: true })
  setChunkSettings(state.settings.chunking)
  toggleChunkFields()
  togglePurposeFields(state.purposes)
  setStage('selecting')

  $$('[data-upload-nav]').forEach(button => {
    button.onclick = () => setStage(button.dataset.uploadNav)
  })
  $('#back-to-metadata').onclick = () => setStage('reviewing-metadata')
  $('#back-to-index').onclick = () => setStage('reviewing-index')
  $('#back-to-confirmed-metadata').onclick = () => setStage('reviewing-metadata')
  $('#chunk-mode').onchange = toggleChunkFields

  $('#knowledge-file').onchange = event => {
    void discardPreview()
    clearMetadataForm(event.target.files[0])
    setStage('selecting')
  }

  $('#document-purpose').onchange = () => {
    const purpose = selectedPurpose(state.purposes)
    if (purpose) setChunkSettings(purposeSettings(purpose))
    togglePurposeFields(state.purposes)
    if (workflow.indexPurposeId && purpose?.id !== workflow.indexPurposeId) invalidateIndex()
  }

  $('#parse-document').onclick = async () => {
    const file = $('#knowledge-file').files[0]
    if (!file) {
      showError('#parse-error', '请先选择需要解析的文件。')
      $('#knowledge-file').focus()
      return
    }
    const button = $('#parse-document')
    clearError('#parse-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = '正在解析正文…'
    try {
      await discardPreview()
      workflow.preview = await previewKnowledge({
        fileName: file.name,
        mimeType: file.type,
        fileBase64: await fileToBase64(file),
      })
      $('#parse-summary').textContent = `${workflow.preview.fileName} · ${workflow.preview.characters.toLocaleString()} 字符 · 正文解析成功`
      setStage('reviewing-metadata')
    } catch (error) {
      showError('#parse-error', `正文解析失败：${error.message}`)
    } finally {
      button.disabled = false
      button.removeAttribute('aria-busy')
      button.textContent = '解析正文'
    }
  }

  $('#analyze-metadata').onclick = async () => {
    if (!workflow.preview) return
    const button = $('#analyze-metadata')
    clearError('#metadata-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = 'AI 分析中…'
    try {
      const result = await analyzeKnowledge(workflow.preview.id)
      workflow.metadata = result.metadata
      applyMetadataSuggestion(result.metadata, state.purposes)
      const purpose = selectedPurpose(state.purposes)
      if (purpose) setChunkSettings(purposeSettings(purpose))
    } catch (error) {
      showError('#metadata-error', `AI 分析失败：${error.message}。可重新分析或手工填写。`)
    } finally {
      button.disabled = false
      button.removeAttribute('aria-busy')
      button.textContent = '使用 AI 分析'
    }
  }

  $('#metadata-continue').onclick = async () => {
    clearError('#metadata-error')
    const invalid = validateMetadata(state.purposes)
    if (invalid) {
      invalid.setAttribute('aria-invalid', 'true')
      showError('#metadata-error', invalid.id === 'document-title' ? '请填写文档标题。' : invalid.id === 'document-purpose' ? '请选择并确认文档用途。' : '请填写模板家族。')
      invalid.focus()
      return
    }
    const purpose = selectedPurpose(state.purposes)
    const button = $('#metadata-continue')
    workflow.confirmedMetadata = collectMetadata(workflow.metadata?.outline || [])
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = purpose.chunkBody ? '正在生成索引预览…' : '正在准备索引预览…'
    try {
      if (purpose.chunkBody) {
        const result = await rechunkKnowledge(workflow.preview.id, collectChunkSettings())
        workflow.chunks = result.chunks
        renderChunkPreview(workflow.chunks)
        $('#preview-summary').textContent = `${result.characters.toLocaleString()} 字符 · ${workflow.chunks.length} 块`
      } else {
        workflow.chunks = []
      }
      workflow.indexPurposeId = purpose.id
      renderReviewIndex(purpose)
      setStage('reviewing-index')
    } catch (error) {
      showError('#metadata-error', `索引预览生成失败：${error.message}`)
    } finally {
      button.disabled = false
      button.removeAttribute('aria-busy')
      button.textContent = '确认属性并继续'
    }
  }

  $('#rechunk-button').onclick = async () => {
    const purpose = selectedPurpose(state.purposes)
    if (!workflow.preview || !purpose?.chunkBody) return
    const button = $('#rechunk-button')
    clearError('#index-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = '正在重新切块…'
    try {
      const result = await rechunkKnowledge(workflow.preview.id, collectChunkSettings())
      workflow.chunks = result.chunks
      workflow.indexPurposeId = purpose.id
      renderChunkPreview(workflow.chunks)
      $('#preview-summary').textContent = `${result.characters.toLocaleString()} 字符 · ${workflow.chunks.length} 块`
      $('#index-continue').disabled = false
    } catch (error) {
      showError('#index-error', `重新切块失败：${error.message}`)
    } finally {
      button.disabled = false
      button.removeAttribute('aria-busy')
      button.textContent = '重新切块'
    }
  }

  $('#index-continue').onclick = () => {
    const purpose = selectedPurpose(state.purposes)
    clearError('#index-error')
    if (!purpose || purpose.id !== workflow.indexPurposeId) {
      showError('#index-error', '用途已变化，请返回确认属性并重新生成索引预览。')
      return
    }
    if (purpose.chunkBody && !hasEnabledChunk()) {
      showError('#index-error', '参考知识至少需要启用一个正文分块。')
      $('#chunk-preview').focus()
      return
    }
    workflow.chunks = purpose.chunkBody ? collectPreviewChunks() : []
    renderFinalSummary(purpose)
    setStage('confirming')
  }
}
