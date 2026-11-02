import { $, escapeHtml } from '../../core/dom.js'
import { statusLabel } from '../../core/format.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction, openDialog } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'
import { categoryOptions } from './categories.js'
import { identity } from '../../core/session.js'
import { beginEdit } from '../reviews/edit-entry.js'

async function refreshDocuments(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

export function purposeLabel(value) { return state.purposes.find(item => item.id === value)?.name || value || '未设置' }

export function indexSummary(document) {
  const template = document.isGenerationTemplate ? `<span>${document.documentIndexed ? '模板索引：已建立' : '模板索引：未建立'}</span>` : ''
  const reference = document.isReferenceKnowledge ? `<span>正文索引：${document.chunkIndexed ? `${document.chunkCount} 块` : '未建立'}</span>` : '<span>正文分块：不适用</span>'
  return `<div class="index-summary">${template}${reference}</div>`
}

function openDocumentEditor(detail, renderPage) {
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
      const body = {
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
      }
      await request(`/api/documents/${encodeURIComponent(detail.id)}`, { method: 'PUT', body })
    }, { wide: true, successMessage: '文档信息和模板索引已更新', afterSave: () => refreshDocuments(renderPage) })
}

export function openDocument(document, renderPage) {
  request(`/api/documents/${encodeURIComponent(document.id)}`).then(detail => {
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
        <div class="danger-zone"><b>废止文档</b><span>正文和原文件保留备查，不再作为有效资料参与检索。</span><button type="button" id="delete-document" class="button danger">废止</button></div>
      </div>`, async () => {}, { wide: true, readOnly: true })
    if(identity)$('#edit-document').textContent='修改送审'
    $('#edit-document').onclick = () => void currentDialog.close().then(() => identity ? beginEdit('knowledge',detail.id) : openDocumentEditor(detail, renderPage))
    $('#reindex-document').onclick = async event => {
      const button = event.currentTarget
      button.disabled = true
      button.textContent = '正在重建…'
      try {
        await request(`/api/documents/${encodeURIComponent(detail.id)}/reindex`, { method: 'POST' })
        await currentDialog.close()
        await refreshDocuments(renderPage)
        toast('向量索引已重建')
      } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '重建向量索引' }
    }
    $('#delete-document').onclick = async () => {
      if (!await confirmAction('废止这个文档？', '废止后退出有效资料检索，正文和原文件仍保留备查。',{confirmLabel:'废止文档'})) return
      try {
        await request(`/api/documents/${encodeURIComponent(detail.id)}`, { method: 'DELETE' })
        await currentDialog.close()
        await refreshDocuments(renderPage)
        toast('文档已废止')
      } catch (error) { toast(error.message, true) }
    }
  }).catch(error => toast(error.message, true))
}
