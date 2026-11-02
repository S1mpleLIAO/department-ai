import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { requiresReview, applyPermissions } from '../../core/session.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction, openDialog } from '../../ui/dialog.js'
import { bindFormLabels, validateDialogForm } from '../../ui/form.js'
import { toast } from '../../ui/feedback.js'
import { categoryOptions } from './categories.js'
import { analyzeKnowledge, deleteKnowledgePreview, indexKnowledge, previewKnowledge, rechunkKnowledge } from './upload-api.js'
import { BATCH_PREPARE_CONCURRENCY, createBatchItems, evaluateBatchItem, mergeSuggestion, runBatchPool } from './upload-batch-state.js'
import { bindInlineCategoryCreator, collectMetadata, inlineCategoryCreatorHtml, metadataFormHtml, togglePurposeFields, validateMetadata } from './upload-metadata.js'
import { chunkPanelHtml, collectChunkSettings, collectPreviewChunks, renderChunkPreview, setChunkSettings, toggleChunkFields, validatePreviewChunks } from './upload-chunks.js'

const statusLabels = { waiting: '等待解析', parsing: '正在解析', analyzing: '正在分析', rechunking: '正在生成索引预览', 'needs-review': '需要确认', ready: '可入库', indexing: '正在入库', completed: '已入库', failed: '失败' }
const retryLabels = { prepare: '重试解析', analyze: '重试分析', rechunk: '重新生成索引预览', index: '重试入库' }

export function openBatchKnowledgeUpload(files, renderPage, { categoryId = '' } = {}) {
  const review=requiresReview('knowledge')
  const completedLabel=review?'已保存草稿':'已入库'
  const readyLabel=review?'可保存':'可入库'
  const labels={...statusLabels,ready:readyLabel,indexing:review?'正在保存草稿':'正在入库',completed:completedLabel}
  const items = createBatchItems(files, categoryId)
  const pending = new Set()
  const busy = new Set()
  const preparationWaiters = []
  let preparationCount = 0
  let disposed = false
  let preparing = true
  let submitting = false
  let creatingCategory = false
  let bulkWorking = false
  let categoryTargets = []
  let confirmingClose = false
  let filter = 'all'
  let detailItem = null
  let returnFocusId = ''
  const categoryCreator = inlineCategoryCreatorHtml('batch')
  const currentDialog = openDialog(review?'批量上传知识草稿':'批量知识入库', review?'确认属性后批量保存草稿，再到提交与审核中提交；发布前不会进入知识检索':'先确认需要处理的文件，再将勾选的可入库文件逐份入库', `
    <div class="batch-upload-summary" aria-live="polite" aria-atomic="true"></div>
    <div id="batch-review">
      <div class="batch-upload-toolbar">
        <div class="field"><label for="batch-filter">显示文件</label><select id="batch-filter"><option value="all">全部</option><option value="needs-review">需要确认</option><option value="failed">失败</option></select></div>
        <label class="batch-upload-selection"><input id="batch-select-all" type="checkbox">选择本批可编辑文件</label>
        <div class="field"><label for="batch-category">批量设置目录</label><select id="batch-category"><option value="">未分类</option>${categoryOptions(categoryId)}</select><button type="button" class="button small" id="batch-apply-category">应用目录</button>${categoryCreator.trigger}</div>
        <div class="field"><label for="batch-purpose">批量设置用途</label><select id="batch-purpose"><option value="">选择用途</option>${purposeOptions()}</select><button type="button" class="button small" id="batch-apply-purpose">应用用途</button></div>
      </div>
      ${categoryCreator.panel}
      <div class="batch-upload-actions"><button type="button" class="button" id="batch-reanalyze">重新分析选中失败项</button><button type="button" class="button" id="batch-remove-selected">移除选中未保存项</button></div>
      <div class="batch-upload-list"></div>
    </div>
    <section class="batch-upload-detail" aria-labelledby="batch-detail-title" hidden></section>
    <p id="batch-error" class="field-error" role="alert" hidden></p>
    <div class="batch-upload-actions"><button type="button" class="button" id="batch-close">${review?'关闭批量上传':'关闭批量入库'}</button>${review?'<a class="button" href="#reviews" id="batch-to-reviews">前往提交与审核</a>':''}<button type="button" class="button primary" id="batch-confirm">确认并入库 0 份</button></div>
  `, async () => {}, { wide: true, readOnly: true })
  const root = currentDialog.element
  const summary = $('.batch-upload-summary', root)
  const list = $('.batch-upload-list', root)
  const detail = $('.batch-upload-detail', root)
  const editable = item => !busy.has(item.id) && !['waiting', 'parsing', 'analyzing', 'rechunking', 'indexing', 'completed'].includes(item.status)
  const selectable = item => editable(item)
  const selectedActionItems = () => items.filter(item => item.selected && selectable(item))
  const selectedEditableItems = () => selectedActionItems().filter(item => item.preview)
  const active = () => pending.size > 0 || submitting
  const actionsLocked = () => submitting || creatingCategory || bulkWorking

  function purposeOptions(selected = '') {
    return state.purposes.map(purpose => `<option value="${escapeHtml(purpose.id)}" ${purpose.id === selected ? 'selected' : ''}>${escapeHtml(purpose.name)}</option>`).join('')
  }

  function track(operation) {
    const promise = operation()
    pending.add(promise)
    void promise.then(() => pending.delete(promise), () => pending.delete(promise))
    return promise
  }

  async function runPreparation(operation) {
    if (disposed) return
    if (preparationCount === BATCH_PREPARE_CONCURRENCY) await new Promise(resolve => preparationWaiters.push(resolve))
    else preparationCount += 1
    try { if (!disposed) return await operation() } finally {
      const next = preparationWaiters.shift()
      if (next) next()
      else preparationCount -= 1
    }
  }

  async function workOn(item, operation) {
    if (disposed || busy.has(item.id) || item.status === 'completed') return
    busy.add(item.id)
    try { await operation(item) } finally { busy.delete(item.id); render() }
  }

  function render() {
    if (disposed) return
    const counts = name => items.filter(item => item.status === name).length
    summary.textContent = `共 ${items.length} 份 · ${readyLabel} ${counts('ready')} · 需要确认 ${counts('needs-review')} · 失败 ${counts('failed')} · ${completedLabel} ${counts('completed')} · 处理中 ${busy.size}`
    const focusId = list.contains(document.activeElement) ? document.activeElement.id : ''
    const rank = item => ['needs-review', 'failed'].includes(item.status) ? 0 : item.status === 'completed' ? 2 : 1
    const visible = items.filter(item => filter === 'all' || item.status === filter).sort((a, b) => rank(a) - rank(b))
    list.innerHTML = visible.map(item => {
      const locked = !editable(item) || actionsLocked()
      const id = escapeHtml(item.id)
      const name = escapeHtml(item.file.name)
      return `<article class="batch-upload-row" data-batch-id="${id}">
        <label class="batch-upload-selection"><input id="batch-select-${id}" data-batch-select type="checkbox" ${item.selected ? 'checked' : ''} ${locked ? 'disabled' : ''} aria-label="选择 ${name}" aria-describedby="batch-error-${id}"><span>${name}</span></label>
        <div class="batch-upload-state"><span>${escapeHtml(item.metadata.title)}</span><small>用途：${escapeHtml(state.purposes.find(purpose => purpose.id === item.metadata.purposeId)?.name || '待确认')}</small><span class="batch-upload-status" data-status="${item.status}">${labels[item.status]}</span><small>${item.preview ? '正文已解析' : item.status === 'completed' ? (review?'等待提交审核':'已完成索引') : `${Math.ceil(item.file.size / 1024)} KB`}</small></div>
        <div class="field"><label for="batch-category-${id}">目录</label><select id="batch-category-${id}" data-batch-category ${locked ? 'disabled' : ''}><option value="">未分类</option>${categoryOptions(item.metadata.categoryId)}</select></div>
        <div class="batch-upload-row-actions"><button type="button" class="button small" id="batch-detail-${id}" data-batch-detail aria-controls="batch-detail-panel" ${locked || !item.preview ? 'disabled' : ''}>查看并确认</button>
          ${item.retryAction && ['failed', 'needs-review'].includes(item.status) ? `<button type="button" class="button small" id="batch-retry-${id}" data-batch-retry ${locked || preparing || busy.size >= 2 ? 'disabled' : ''}>${retryLabels[item.retryAction]}</button>` : ''}
          <button type="button" class="button small" id="batch-remove-${id}" data-batch-remove ${locked ? 'disabled' : ''}>移除</button></div>
        <p class="field-error batch-upload-error" id="batch-error-${id}">${escapeHtml(item.error)}</p>
      </article>`
    }).join('') || '<div class="empty compact">没有符合筛选条件的文件</div>'
    $$('.batch-upload-row', list).forEach(row => {
      const item = items.find(value => value.id === row.dataset.batchId)
      $('[data-batch-select]', row).onchange = event => { item.selected = event.target.checked; render() }
      $('[data-batch-category]', row).onchange = event => { item.metadata.categoryId = event.target.value }
      $('[data-batch-detail]', row).onclick = () => openDetail(item)
      $('[data-batch-remove]', row).onclick = () => void track(() => workOn(item, removeItem))
      const retry = $('[data-batch-retry]', row)
      if (retry) retry.onclick = () => {
        if (actionsLocked() || preparing || busy.size >= 2) return
        if (item.retryAction === 'index') void submitItems([item])
        else void track(() => workOn(item, async () => {
          if (item.retryAction === 'prepare') await prepare(item)
          else if (item.retryAction === 'analyze') await analyzeThenPrepareIndex(item)
          else if (item.retryAction === 'rechunk') await rechunkThenEvaluate(item)
        }))
      }
    })
    const selectableItems = items.filter(selectable)
    const selected = selectedActionItems().length
    const all = $('#batch-select-all', root)
    all.checked = selectableItems.length > 0 && selectableItems.length === selected
    all.indeterminate = selected > 0 && selected < selectableItems.length
    all.disabled = actionsLocked() || !selectableItems.length
    const metadataSelected = selectedEditableItems().length
    $('#batch-apply-category', root).disabled = actionsLocked() || !metadataSelected
    $('#batch-apply-purpose', root).disabled = actionsLocked() || !metadataSelected
    $('#batch-category-create', root).disabled = actionsLocked() || !metadataSelected
    $('#batch-category', root).disabled = actionsLocked()
    $('#batch-reanalyze', root).disabled = actionsLocked() || preparing || !selectedEditableItems().some(item => item.retryAction === 'analyze')
    $('#batch-remove-selected', root).disabled = actionsLocked() || !selected
    const readyCount = items.filter(item => item.selected && item.status === 'ready').length
    const confirm = $('#batch-confirm', root)
    confirm.textContent = `${review?'保存草稿':'确认并入库'} ${readyCount} 份`
    confirm.disabled = actionsLocked() || preparing || !!detailItem || !readyCount
    confirm.setAttribute('aria-busy', String(submitting))
    applyPermissions(root)
    if(review)$('#document-status',root)?.closest('.field')?.setAttribute('hidden','')
    if (focusId) (document.getElementById(focusId) || $('#batch-filter', root)).focus()
    const returnControl = returnFocusId && document.getElementById(returnFocusId)
    if (returnControl && !returnControl.disabled) { returnControl.focus(); returnFocusId = '' }
    else if (returnFocusId && !returnControl) { $('#batch-filter', root).focus(); returnFocusId = '' }
  }

  function chunkSettingsFor(purpose) {
    return purpose.inheritChunking ? state.settings.chunking : purpose.chunkSettings || state.settings.chunking
  }

  async function rechunkThenEvaluate(item) {
    const purpose = state.purposes.find(value => value.id === item.metadata.purposeId)
    if (!purpose) { evaluateBatchItem(item, state.purposes); render(); return }
    if (!purpose.chunkBody) { item.chunks = []; item.chunkSettings = null; evaluateBatchItem(item, state.purposes); render(); return }
    item.retryAction = 'rechunk'
    item.status = 'rechunking'
    render()
    try {
      const result = await runPreparation(() => rechunkKnowledge(item.preview.id, chunkSettingsFor(purpose)))
      if (disposed) return
      item.chunks = result.chunks
      item.chunkSettings = chunkSettingsFor(purpose)
      evaluateBatchItem(item, state.purposes)
    } catch (error) {
      item.status = 'needs-review'
      item.error = `分块失败：${error.message}`
      item.selected = false
    }
    render()
  }

  async function analyzeThenPrepareIndex(item) {
    item.retryAction = 'analyze'
    item.status = 'analyzing'
    render()
    try {
      const result = await runPreparation(() => analyzeKnowledge(item.preview.id, { suggestCategory: item.entryCategoryId === '' }))
      if (disposed) return
      mergeSuggestion(item, result.metadata, state.purposes, state.categories)
    } catch (error) {
      item.status = 'needs-review'
      item.error = `AI 分析失败：${error.message}`
      item.retryAction = 'analyze'
      item.selected = false
      render()
      return
    }
    await rechunkThenEvaluate(item)
  }

  async function prepare(item) {
    item.retryAction = 'prepare'
    item.status = 'parsing'
    render()
    try { item.preview = await runPreparation(() => previewKnowledge(item.file)) } catch (error) {
      item.status = 'failed'
      item.error = `正文解析失败：${error.message}`
      item.selected = false
      render()
      return
    }
    if (!disposed) await analyzeThenPrepareIndex(item)
  }

  async function removeItem(item) {
    render()
    try {
      if (item.preview) await deleteKnowledgePreview(item.preview.id)
      item.preview = null
      items.splice(items.indexOf(item), 1)
    } catch (error) { item.error = `临时文件清理失败：${error.message}。请重试移除。` }
  }

  function closeDetail() {
    const id = detailItem.id
    returnFocusId = `batch-detail-${id}`
    detailItem = null
    detail.hidden = true
    detail.innerHTML = ''
    $('#batch-review', root).hidden = false
    render()
  }

  function openDetail(item) {
    detailItem = item
    $('#batch-review', root).hidden = true
    detail.hidden = false
    detail.id = 'batch-detail-panel'
    detail.innerHTML = `<h3 id="batch-detail-title" tabindex="-1">确认 ${escapeHtml(item.file.name)}</h3>
      <p class="muted small-copy">正文已解析 · ${item.preview.characters.toLocaleString()} 字符</p>
      ${metadataFormHtml({ documentId: item.metadata.id, categoryOptionsHtml: categoryOptions(item.metadata.categoryId), purposes: state.purposes })}
      <span id="preview-button" hidden></span>${chunkPanelHtml(state.settings.chunking)}
      <div id="chunk-preview" class="chunk-preview"></div>
      <p id="batch-detail-error" class="field-error" role="alert" hidden></p>
      <div class="batch-upload-actions"><button type="button" class="button" id="batch-detail-cancel">返回列表</button><button type="button" class="button primary" id="batch-detail-save">保存确认</button></div>`
    const fields = { 'document-title': 'title', 'document-purpose': 'purposeId', 'document-type': 'documentType', 'document-category': 'categoryId', 'document-status': 'status', 'document-summary': 'summary', 'template-family': 'templateFamily', 'template-variant': 'templateVariant', 'template-version': 'version', 'template-scenario': 'applicableScenario' }
    Object.entries(fields).forEach(([id, key]) => { document.getElementById(id).value = item.metadata[key] })
    $('#document-keywords').value = item.metadata.keywords.join('、')
    let purpose = state.purposes.find(value => value.id === item.metadata.purposeId)
    const savedSettings = item.chunkSettings || (purpose ? chunkSettingsFor(purpose) : state.settings.chunking)
    const initialChunking = purpose?.chunkBody ? JSON.stringify(savedSettings) : ''
    setChunkSettings(savedSettings)
    togglePurposeFields(state.purposes)
    renderChunkPreview(item.chunks)
    bindFormLabels(detail)
    $$('.chunk-content', detail).forEach((control, index) => control.setAttribute('aria-label', `分块 ${index + 1} 正文`))
    bindInlineCategoryCreator(() => {
      const select = $('#batch-category', root)
      const selected = select.value
      select.innerHTML = `<option value="">未分类</option>${categoryOptions(selected)}`
    }, {
      isCurrent: () => !disposed && detailItem === item,
      run: operation => track(() => workOn(item, async () => {
        const actions = [$('#batch-detail-save', detail), $('#batch-detail-cancel', detail)]
        actions.forEach(button => { button.disabled = true })
        try { await operation() } finally {
          if (!disposed && detailItem === item) actions.forEach(button => { button.disabled = false })
        }
      })),
    })
    $('#chunk-mode').onchange = toggleChunkFields
    $('#document-purpose').onchange = () => {
      purpose = state.purposes.find(value => value.id === $('#document-purpose').value)
      if (purpose) setChunkSettings(chunkSettingsFor(purpose))
      togglePurposeFields(state.purposes)
    }
    $('#batch-detail-cancel').onclick = closeDetail
    $('#batch-detail-save').onclick = () => void track(() => workOn(item, async () => {
      const errorNode = $('#batch-detail-error')
      errorNode.hidden = true
      const invalid = validateMetadata(state.purposes)
      if (invalid || !validateDialogForm(detail)) {
        if (invalid) {
          errorNode.textContent = '请确认标题、用途和所需模板家族'
          errorNode.hidden = false
          invalid.setAttribute('aria-invalid', 'true')
          invalid.setAttribute('aria-describedby', 'batch-detail-error')
          invalid.focus()
        }
        return
      }
      const controls = $$('input, select, textarea, button', detail)
      const disabledStates = controls.map(control => control.disabled)
      const settings = collectChunkSettings()
      const metadata = collectMetadata(item.metadata.outline)
      purpose = state.purposes.find(value => value.id === metadata.purposeId)
      const mustRechunk = purpose.chunkBody && (initialChunking !== JSON.stringify(settings) || item.chunks.length === 0)
      const chunks = collectPreviewChunks()
      if (purpose.chunkBody && !mustRechunk && !validatePreviewChunks(errorNode)) return
      controls.forEach(control => { control.disabled = true })
      $('#batch-detail-save').setAttribute('aria-busy', 'true')
      try {
        if (mustRechunk) {
          item.status = 'rechunking'
          render()
          const result = await runPreparation(() => rechunkKnowledge(item.preview.id, settings))
          if (disposed) return
          item.chunks = result.chunks
        } else item.chunks = purpose.chunkBody ? chunks : []
        item.chunkSettings = purpose.chunkBody ? settings : null
        item.metadata = metadata
        evaluateBatchItem(item, state.purposes)
        closeDetail()
      } catch (error) {
        if (disposed) return
        item.status = 'needs-review'
        item.selected = false
        item.error = `分块失败：${error.message}。请打开详情重新确认索引预览。`
        errorNode.textContent = `分块失败：${error.message}。保留了输入，请重试保存确认。`
        errorNode.hidden = false
      } finally {
        if (!disposed) {
          controls.forEach((control, index) => { control.disabled = disabledStates[index] })
          $('#batch-detail-save', detail)?.removeAttribute('aria-busy')
        }
      }
    }))
    render()
    $('#batch-detail-title').focus()
  }

  async function indexOne(item) {
    item.status = 'indexing'
    item.retryAction = 'index'
    render()
    try {
      await indexKnowledge(item.preview.id, { ...item.metadata, chunks: item.chunks })
      item.preview = null
      item.status = 'completed'
      item.selected = false
      item.error = ''
      item.retryAction = ''
    } catch (error) {
      item.status = 'failed'
      item.selected = false
      item.error = `保存失败：${error.message}`
    }
    render()
  }

  async function refreshKnowledgePage() {
    if (disposed) return
    const nextState = await request('/api/state')
    if (disposed) return
    replaceState(nextState)
    renderPage()
  }

  async function submitItems(selected) {
    if (actionsLocked() || disposed) return
    submitting = true
    render()
    await track(async () => {
      for (const item of selected) {
        if (disposed) break
        await workOn(item, indexOne)
      }
      try { await refreshKnowledgePage() } catch (error) {
        if (!disposed) {
          $('#batch-error', root).textContent = `列表刷新失败：${error.message}。保存结果已保留，可关闭后刷新页面。`
          $('#batch-error', root).hidden = false
        }
      }
    })
    submitting = false
    render()
  }

  async function requestClose() {
    if (disposed || confirmingClose) return
    confirmingClose = true
    try {
      if (active() && !await confirmAction('关闭批量上传？', '正在处理的请求会结束，剩余文件将停止处理并清理临时预览；已经保存的内容会保留。',{confirmLabel:'关闭上传'})) return false
      disposed = true
      await currentDialog.close()
      return true
    } finally { confirmingClose = false }
  }
  const interceptClick = event => {
    if (!event.target.closest?.('.dialog-close')) return
    event.preventDefault()
    event.stopImmediatePropagation()
    void requestClose()
  }
  const interceptCancel = event => {
    event.preventDefault()
    event.stopImmediatePropagation()
    void requestClose()
  }
  root.addEventListener('click', interceptClick, true)
  root.addEventListener('cancel', interceptCancel, true)
  root.addEventListener('close', async () => {
    disposed = true
    root.removeEventListener('click', interceptClick, true)
    root.removeEventListener('cancel', interceptCancel, true)
    await Promise.allSettled([...pending])
    for (const item of items) {
      if (!item.preview) continue
      const id = item.preview.id
      item.preview = null
      try { await deleteKnowledgePreview(id) } catch (error) { toast(`临时预览清理失败：${item.file.name} · ${error.message}`, true) }
    }
  }, { once: true })
  $('#batch-close', root).onclick = () => void requestClose()
  if(review)$('#batch-to-reviews',root).onclick=async event=>{event.preventDefault();if(await requestClose())location.hash='#reviews'}
  bindInlineCategoryCreator(category => {
    categoryTargets.forEach(item => { item.metadata.categoryId = category.id })
    render()
  }, {
    prefix: 'batch', categorySelect: $('#batch-category', root),
    isCurrent: () => !disposed,
    run: operation => track(async () => {
      categoryTargets = selectedEditableItems()
      creatingCategory = true
      render()
      try { await operation() } finally { creatingCategory = false; render() }
    }),
  })
  $('#batch-reanalyze', root).onclick = () => {
    if (actionsLocked() || preparing || disposed) return
    const selected = selectedEditableItems().filter(item => item.retryAction === 'analyze')
    bulkWorking = true
    render()
    void track(async () => {
      try { await runBatchPool(selected, item => workOn(item, analyzeThenPrepareIndex)) }
      finally { bulkWorking = false; render() }
    })
  }
  $('#batch-remove-selected', root).onclick = () => {
    if (actionsLocked() || disposed) return
    const selected = selectedActionItems()
    bulkWorking = true
    render()
    void track(async () => {
      try {
        for (const item of selected) {
          if (disposed) break
          await workOn(item, removeItem)
        }
      } finally { bulkWorking = false; render() }
    })
  }
  $('#batch-filter', root).onchange = event => { filter = event.target.value; render() }
  $('#batch-select-all', root).onchange = event => { items.filter(selectable).forEach(item => { item.selected = event.target.checked }); render() }
  $('#batch-apply-category', root).onclick = () => {
    selectedEditableItems().forEach(item => { item.metadata.categoryId = $('#batch-category', root).value })
    render()
  }
  $('#batch-apply-purpose', root).onclick = () => {
    const purposeId = $('#batch-purpose', root).value
    const purpose = state.purposes.find(value => value.id === purposeId)
    if (!purpose) { $('#batch-purpose', root).focus(); return }
    for (const item of selectedEditableItems()) {
      if (item.metadata.purposeId === purposeId) continue
      item.metadata.purposeId = purposeId
      item.chunks = []
      item.chunkSettings = null
      item.selected = false
      item.status = 'needs-review'
      item.error = '用途已修改，请重新生成索引预览'
      item.retryAction = purpose.chunkBody ? 'rechunk' : ''
      if (!purpose.chunkBody) evaluateBatchItem(item, state.purposes)
    }
    render()
  }
  $('#batch-confirm', root).onclick = () => void submitItems(items.filter(item => item.selected && item.status === 'ready'))
  render()
  void track(async () => {
    await runBatchPool(items, item => workOn(item, prepare))
    preparing = false
    render()
  })
}
