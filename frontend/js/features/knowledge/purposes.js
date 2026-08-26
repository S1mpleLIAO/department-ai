import { $, $$, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction, dialogContent, openDialog } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'

async function refreshPurposes(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

export function chunkSettingsForm(settings) {
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

export function collectChunkSettings() {
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

export function setChunkSettings(settings) {
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

export function chunkSettingsSummary(settings) {
  const preprocessing = [settings.cleanWhitespace ? '合并空格与多余换行' : '', settings.removeUrlsEmails ? '删除 URL 与邮箱' : '保留 URL 与邮箱'].filter(Boolean).join(' · ')
  return settings.mode === 'parent-child'
    ? `${chunkModeLabel(settings.mode)} · 父块 ${settings.parentMaxTokens} Token · 子块 ${settings.childMaxTokens} Token · 子块重叠 ${settings.childOverlapTokens} Token · ${preprocessing}`
    : `${chunkModeLabel(settings.mode)} · 每块最大 ${settings.maxTokens} Token · 重叠 ${settings.overlapTokens} Token · ${preprocessing}`
}

export function toggleChunkFields() {
  const mode = $('#chunk-mode').value
  $$('.standard-setting').forEach(node => node.hidden = mode === 'parent-child')
  $$('.parent-setting').forEach(node => node.hidden = mode !== 'parent-child')
  $$('.general-setting').forEach(node => node.hidden = mode !== 'general')
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

function openPurposeEditor(purpose, renderPage) {
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
      const body = {
        name: $('#purpose-name').value.trim(),
        description: $('#purpose-description').value.trim(),
        canGenerateTemplate: $('#purpose-template').checked,
        chunkBody: $('#purpose-chunk-body').checked,
        inheritChunking: $('#purpose-inherit-chunking').checked,
        chunkSettings: collectChunkSettings(),
      }
      const path = purpose ? `/api/purposes/${encodeURIComponent(purpose.id)}` : '/api/purposes'
      await request(path, { method: purpose ? 'PUT' : 'POST', body })
    }, { wide: true, successMessage: purpose ? '文档用途已更新' : '文档用途已创建', afterSave: () => refreshPurposes(renderPage) })
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

function bindPurposeManager(currentDialog, renderPage) {
  $('#add-purpose', dialogContent).onclick = () => void currentDialog.close().then(() => openPurposeEditor(undefined, renderPage))
  $$('.edit-purpose', dialogContent).forEach(button => button.onclick = () => void currentDialog.close().then(() => openPurposeEditor(state.purposes.find(item => item.id === button.dataset.id), renderPage)))
  $$('.delete-purpose', dialogContent).forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个文档用途吗？', '正在被文档使用的用途不会被删除。')) return
    try {
      await request(`/api/purposes/${encodeURIComponent(button.dataset.id)}`, { method: 'DELETE' })
      replaceState(await request('/api/state'))
      dialogContent.innerHTML = purposeManagerHtml()
      bindPurposeManager(currentDialog, renderPage)
      toast('文档用途已删除')
    } catch (error) { toast(error.message, true) }
  })
}

export function openPurposeManager(renderPage) {
  const currentDialog = openDialog('管理文档用途', '在上传文档前维护用途和对应的索引规则。', purposeManagerHtml(), async () => {}, { wide: true, readOnly: true })
  bindPurposeManager(currentDialog, renderPage)
}
