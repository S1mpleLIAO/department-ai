import { $, $$, escapeHtml } from './js/core/dom.js'
import { formatDate, statusLabel } from './js/core/format.js'
import { request } from './js/core/http.js'
import { replaceState, state } from './js/core/state.js'
import { renderAssistant } from './js/features/assistant.js'
import { renderDashboard } from './js/features/dashboard.js'
import { renderProcesses } from './js/features/processes/index.js'
import { chunkSettingsForm, chunkSettingsSummary, collectChunkSettings, renderSettings, setChunkSettings, toggleChunkFields } from './js/features/settings.js'
import { renderSkills } from './js/features/skills/index.js'
import { confirmAction, dialogContent, openDialog } from './js/ui/dialog.js'
import { setAction, setSecondaryAction, toast } from './js/ui/feedback.js'

const content = $('#content')
const pageTitle = $('#page-title')
const pageSubtitle = $('#page-subtitle')
const assistantHost = $('#assistant-host')

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

function purposeLabel(value) { return state.purposes.find(item => item.id === value)?.name || value || '未设置' }

function getState() { return request('/api/state') }
function saveCategory(body) {
  const method = body.create ? 'POST' : 'PUT'
  const path = body.create ? '/api/categories' : `/api/categories/${encodeURIComponent(body.id)}`
  return request(path, { method, body: { name: body.name, parentId: body.parentId || null } })
}
function deleteCategory(id) { return request(`/api/categories/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
function savePurpose(body) {
  const method = body.id ? 'PUT' : 'POST'
  const path = body.id ? `/api/purposes/${encodeURIComponent(body.id)}` : '/api/purposes'
  const payload = { ...body }; delete payload.id
  return request(path, { method, body: payload })
}
function deletePurpose(id) { return request(`/api/purposes/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
function previewKnowledge(body) { return request('/api/knowledge/preview', { method: 'POST', body }) }
function rechunkKnowledge(previewId, chunkSettings) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/rechunk`, { method: 'POST', body: chunkSettings }) }
function indexKnowledge(body) {
  const path = `/api/knowledge/previews/${encodeURIComponent(body.previewId)}/index`
  const payload = { ...body }; delete payload.previewId
  return request(path, { method: 'POST', body: payload })
}
function getDocument(id) { return request(`/api/documents/${encodeURIComponent(id)}`) }
function deleteDocument(id) { return request(`/api/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
function updateDocument(body) {
  const payload = { ...body }; delete payload.id
  return request(`/api/documents/${encodeURIComponent(body.id)}`, { method: 'PUT', body: payload })
}
function reindexDocument(id) { return request(`/api/documents/${encodeURIComponent(id)}/reindex`, { method: 'POST' }) }
function deleteKnowledgePreview(previewId) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}`, { method: 'DELETE' }) }

async function refresh() { replaceState(await getState()) }
async function afterDialogSave() { await refresh(); renderPage() }

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
  const currentDialog = openDialog(category ? '编辑知识目录' : '新建知识目录', '目录可以随时新增、重命名和移动', `
    <div class="form-grid">
      <div class="field full"><label>目录名称</label><input id="category-name" value="${escapeHtml(current.name)}" placeholder="网络"></div>
      <div class="field"><label>上级目录</label><select id="category-parent"><option value="">根目录</option>${categoryOptions(current.parentId || '', current.id)}</select></div>
      <p class="muted small-copy">新目录会自动排在同级目录末尾；移动目录时，下面的子目录和文档会一起保留。</p>
    </div>
    ${category ? '<div class="danger-zone"><b>删除目录</b><span>只有没有子目录和文档时才能删除。</span><button type="button" id="delete-category" class="button danger">删除</button></div>' : ''}`, async () => {
      const result = await saveCategory({ id: category?.id || '', create: !category, name: $('#category-name').value.trim(), parentId: $('#category-parent').value })
      activeCategory = result.category.id
    }, { afterSave: afterDialogSave })
  if (category) $('#delete-category').onclick = async () => {
    if (!await confirmAction('确定删除这个目录吗？', '只有空目录可以删除。')) return
    try { await deleteCategory(category.id); await currentDialog.close(); activeCategory = ''; await refresh(); renderPage(); toast('目录已删除') } catch (error) { toast(error.message, true) }
  }
}

function purposeChunkSummary(purpose) {
  if (!purpose.chunkBody) return '不建立正文分块'
  if (purpose.inheritChunking) return '继承系统默认分块设置'
  return chunkSettingsSummary(purpose.chunkSettings)
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
      await savePurpose({
        id: purpose?.id,
        name: $('#purpose-name').value.trim(),
        description: $('#purpose-description').value.trim(),
        canGenerateTemplate: $('#purpose-template').checked,
        chunkBody: $('#purpose-chunk-body').checked,
        inheritChunking: $('#purpose-inherit-chunking').checked,
        chunkSettings: collectChunkSettings(),
      })
    }, { wide: true, successMessage: purpose ? '文档用途已更新' : '文档用途已创建', afterSave: afterDialogSave })
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

function bindPurposeManager(currentDialog) {
  $('#add-purpose', dialogContent).onclick = () => void currentDialog.close().then(() => openPurposeEditor())
  $$('.edit-purpose', dialogContent).forEach(button => button.onclick = () => void currentDialog.close().then(() => openPurposeEditor(state.purposes.find(item => item.id === button.dataset.id))))
  $$('.delete-purpose', dialogContent).forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个文档用途吗？', '正在被文档使用的用途不会被删除。')) return
    try { await deletePurpose(button.dataset.id); await refresh(); dialogContent.innerHTML = purposeManagerHtml(); bindPurposeManager(currentDialog); toast('文档用途已删除') }
    catch (error) { toast(error.message, true) }
  })
}

function openPurposeManager() {
  const currentDialog = openDialog('管理文档用途', '在上传文档前维护用途和对应的索引规则。', purposeManagerHtml(), async () => {}, { wide: true, readOnly: true })
  bindPurposeManager(currentDialog)
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
  }, { wide: true, saveLabel: '确认并建立索引', successMessage: '文档已入库并按用途完成索引', afterSave: afterDialogSave })
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
      await updateDocument({
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
    }, { wide: true, successMessage: '文档信息和模板索引已更新', afterSave: afterDialogSave })
}

function openDocument(document) {
  getDocument(document.id).then(detail => {
    const currentDialog = openDialog(detail.title, `${detail.originalName} · ${detail.chunkCount} 个正文分块`, `
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
    $('#edit-document').onclick = () => void currentDialog.close().then(() => openDocumentEditor(detail))
    $('#reindex-document').onclick = async event => {
      const button = event.currentTarget
      button.disabled = true
      button.textContent = '正在重建…'
      try { await reindexDocument(detail.id); await currentDialog.close(); await refresh(); renderPage(); toast('向量索引已重建') }
      catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '重建向量索引' }
    }
    $('#delete-document').onclick = async () => {
      if (!await confirmAction('确定删除这个文档吗？', '文档记录、向量索引和受管理的原始文件都会被删除。')) return
      try { await deleteDocument(detail.id); await currentDialog.close(); await refresh(); renderPage(); toast('文档已删除') } catch (error) { toast(error.message, true) }
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
  const renderers = {
    dashboard: renderDashboard,
    processes: () => renderProcesses(renderPage),
    knowledge: renderKnowledge,
    skills: () => renderSkills(renderPage),
    assistant: renderAssistant,
    settings: () => renderSettings(renderPage, openPurposeManager),
  }
  ;(renderers[page] || renderDashboard)()
  $('main').scrollTop = 0
}

async function start() {
  content.innerHTML = '<div class="loading">正在连接部门数据库和知识服务…</div>'
  try { await refresh(); renderPage() } catch (error) { content.innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)}</div>` }
}

window.addEventListener('hashchange', renderPage)
start()
