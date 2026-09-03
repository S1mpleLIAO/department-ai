import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { openDialog } from '../../ui/dialog.js'
import { activeCategory, categoryOptions } from './categories.js'
import { bindScopeFields, scopeLabel } from './scope.js'
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
  let lastDocumentId = 0
  const nextDocumentId = () => {
    lastDocumentId = Math.max(Date.now(), lastDocumentId + 1)
    return `knowledge-${lastDocumentId}`
  }
  const workflow = {
    stage: 'selecting', preview: null, metadata: null, chunks: [],
    confirmedMetadata: null, indexPurposeId: '', saving: false, generation: 0, disposed: false,
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
        ${metadataFormHtml({ documentId: nextDocumentId(), categoryOptionsHtml: categoryOptions(activeCategory), purposes: state.purposes, processes: state.processes })}
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
    const generation = workflow.generation
    setStage('saving')
    try {
      await indexKnowledge({
        previewId: workflow.preview.id,
        ...workflow.confirmedMetadata,
        chunks: workflow.chunks,
      })
      if (!isCurrent(generation)) return
      workflow.preview = null
    } catch (error) {
      if (isCurrent(generation)) setStage('confirming')
      throw error
    }
  }, {
    wide: true,
    saveLabel: '确认入库',
    successMessage: '文档已入库并按用途完成索引',
    afterSave: () => refreshUpload(renderPage),
  })
  bindScopeFields('upload', state.processes)

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
    currentDialog.saveButton.disabled = workflow.saving || visibleStage !== 'confirming'
    currentDialog.saveButton.textContent = workflow.saving ? '正在入库…' : '确认入库'
    $$('.dialog-close', currentDialog.element).forEach(button => { button.disabled = workflow.saving })
    if (!workflow.saving) $(`[data-upload-step="${visibleStage}"] h3`)?.focus()
  }

  function isCurrent(generation) {
    return !workflow.disposed && workflow.generation === generation
  }

  function resetAsyncButtons() {
    const buttons = [
      ['#parse-document', '解析正文'],
      ['#analyze-metadata', '使用 AI 分析'],
      ['#metadata-continue', '确认属性并继续'],
      ['#rechunk-button', '重新切块'],
    ]
    buttons.forEach(([selector, label]) => {
      const button = $(selector)
      button.disabled = false
      button.removeAttribute('aria-busy')
      button.textContent = label
    })
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
      '#document-id': nextDocumentId(),
      '#document-title': file?.name.replace(/\.[^.]+$/, '') || '',
      '#document-purpose': '', '#document-type': '', '#document-category': '', '#document-status': 'effective',
      '#document-keywords': '', '#document-summary': '', '#template-family': '', '#template-variant': '',
      '#template-version': 'V1.0', '#upload-task-scenario': '', '#upload-process': '', '#upload-step': '',
    }
    Object.entries(values).forEach(([selector, value]) => {
      const control = $(selector)
      control.value = value
      control.removeAttribute('aria-invalid')
      control.removeAttribute('aria-describedby')
      delete control.dataset.aiSuggested
      control.closest('.field')?.querySelector('.field-error')?.remove()
    })
    $$('input[name="upload-scope-type"]').forEach(control => {
      control.checked = false
      control.removeAttribute('aria-invalid')
      control.removeAttribute('aria-describedby')
      delete control.dataset.aiSuggested
    })
    $('#upload-process').dispatchEvent(new Event('change', { bubbles: true }))
    $('#upload-scope-global').dispatchEvent(new Event('change', { bubbles: true }))
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
      <span>适用范围：${escapeHtml(scopeLabel(metadata, state.processes))}</span>
      ${purpose.canGenerateTemplate ? `<span>模板家族：${escapeHtml(metadata.templateFamily)}</span>` : ''}
      <span>${purpose.chunkBody ? `有效分块：${enabledChunks} 块` : '正文不切块'}</span>
    </div>`
  }

  const preventSavingClose = event => {
    if (!workflow.saving || !(event.target instanceof HTMLElement) || !event.target.closest('.dialog-close')) return
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  const preventSavingCancel = event => {
    if (!workflow.saving) return
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  currentDialog.element.addEventListener('click', preventSavingClose, true)
  currentDialog.element.addEventListener('cancel', preventSavingCancel, true)
  currentDialog.element.addEventListener('close', () => {
    currentDialog.element.removeEventListener('click', preventSavingClose, true)
    currentDialog.element.removeEventListener('cancel', preventSavingCancel, true)
    const shouldDiscard = !workflow.saving
    workflow.disposed = true
    workflow.generation += 1
    if (shouldDiscard) void discardPreview()
  }, { once: true })
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
    if (workflow.saving) return
    workflow.generation += 1
    void discardPreview()
    clearMetadataForm(event.target.files[0])
    resetAsyncButtons()
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
    const generation = workflow.generation
    clearError('#parse-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = '正在解析正文…'
    try {
      await discardPreview()
      if (!isCurrent(generation)) return
      const fileBase64 = await fileToBase64(file)
      if (!isCurrent(generation)) return
      const preview = await previewKnowledge({
        fileName: file.name,
        mimeType: file.type,
        fileBase64,
      })
      if (!isCurrent(generation)) {
        try { await deleteKnowledgePreview(preview.id) } catch (_) {}
        return
      }
      workflow.preview = preview
      $('#parse-summary').textContent = `${preview.fileName} · ${preview.characters.toLocaleString()} 字符 · 正文解析成功`
      setStage('reviewing-metadata')
    } catch (error) {
      if (isCurrent(generation)) showError('#parse-error', `正文解析失败：${error.message}`)
    } finally {
      if (isCurrent(generation)) {
        button.disabled = false
        button.removeAttribute('aria-busy')
        button.textContent = '解析正文'
      }
    }
  }

  $('#analyze-metadata').onclick = async () => {
    if (!workflow.preview) return
    const button = $('#analyze-metadata')
    const generation = workflow.generation
    clearError('#metadata-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = 'AI 分析中…'
    try {
      const result = await analyzeKnowledge(workflow.preview.id)
      if (!isCurrent(generation)) return
      workflow.metadata = result.metadata
      applyMetadataSuggestion(result.metadata, state.purposes, state.processes)
      const purpose = selectedPurpose(state.purposes)
      if (purpose) setChunkSettings(purposeSettings(purpose))
    } catch (error) {
      if (isCurrent(generation)) showError('#metadata-error', `AI 分析失败：${error.message}。可重新分析或手工填写。`)
    } finally {
      if (isCurrent(generation)) {
        button.disabled = false
        button.removeAttribute('aria-busy')
        button.textContent = '使用 AI 分析'
      }
    }
  }

  $('#metadata-continue').onclick = async () => {
    clearError('#metadata-error')
    const metadataPanel = $('[data-upload-step="reviewing-metadata"]')
    const invalid = validateMetadata(state.purposes)
      || $$('input, textarea, select', metadataPanel).find(control => !control.disabled && (
        !control.checkValidity() || control.id === 'document-id' && !/^[a-z0-9][a-z0-9-]{0,63}$/.test(control.value)
      ))
    if (invalid) {
      const scopeMessages = {
        'upload-scope-global': '请选择并确认适用范围。',
        'upload-task-scenario': '请填写独立任务场景。',
        'upload-process': '请选择业务流程。',
        'upload-step': '请选择流程步骤。',
      }
      const errorSelector = scopeMessages[invalid.id] ? '#upload-scope-error' : '#metadata-error'
      invalid.setAttribute('aria-invalid', 'true')
      invalid.setAttribute('aria-describedby', errorSelector.slice(1))
      const messages = {
        'document-title': '请填写文档标题。',
        'document-purpose': '请选择并确认文档用途。',
        'template-family': '请填写模板家族。',
        ...scopeMessages,
      }
      showError(errorSelector, messages[invalid.id] || '请检查文档 ID，只能使用小写字母、数字和连字符。')
      invalid.focus()
      return
    }
    const purpose = selectedPurpose(state.purposes)
    if (!workflow.preview || !purpose) return
    const button = $('#metadata-continue')
    const generation = workflow.generation
    workflow.confirmedMetadata = collectMetadata(workflow.metadata?.outline || [])
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = purpose.chunkBody ? '正在生成索引预览…' : '正在准备索引预览…'
    try {
      if (purpose.chunkBody) {
        const result = await rechunkKnowledge(workflow.preview.id, collectChunkSettings())
        if (!isCurrent(generation)) return
        workflow.chunks = result.chunks
        renderChunkPreview(workflow.chunks)
        $('#preview-summary').textContent = `${result.characters.toLocaleString()} 字符 · ${workflow.chunks.length} 块`
      } else {
        if (!isCurrent(generation)) return
        workflow.chunks = []
      }
      workflow.indexPurposeId = purpose.id
      renderReviewIndex(purpose)
      setStage('reviewing-index')
    } catch (error) {
      if (isCurrent(generation)) showError('#metadata-error', `索引预览生成失败：${error.message}`)
    } finally {
      if (isCurrent(generation)) {
        button.disabled = false
        button.removeAttribute('aria-busy')
        button.textContent = '确认属性并继续'
      }
    }
  }

  $('#rechunk-button').onclick = async () => {
    const purpose = selectedPurpose(state.purposes)
    if (!workflow.preview || !purpose?.chunkBody) return
    const button = $('#rechunk-button')
    const generation = workflow.generation
    clearError('#index-error')
    button.disabled = true
    button.setAttribute('aria-busy', 'true')
    button.textContent = '正在重新切块…'
    try {
      const result = await rechunkKnowledge(workflow.preview.id, collectChunkSettings())
      if (!isCurrent(generation)) return
      workflow.chunks = result.chunks
      workflow.indexPurposeId = purpose.id
      renderChunkPreview(workflow.chunks)
      $('#preview-summary').textContent = `${result.characters.toLocaleString()} 字符 · ${workflow.chunks.length} 块`
      $('#index-continue').disabled = false
    } catch (error) {
      if (isCurrent(generation)) showError('#index-error', `重新切块失败：${error.message}`)
    } finally {
      if (isCurrent(generation)) {
        button.disabled = false
        button.removeAttribute('aria-busy')
        button.textContent = '重新切块'
      }
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
      $('.chunk-enabled:not(:disabled)', $('#chunk-preview'))?.focus()
      return
    }
    workflow.chunks = purpose.chunkBody ? collectPreviewChunks() : []
    renderFinalSummary(purpose)
    setStage('confirming')
  }
}
