import { $, $$, escapeHtml } from '../../core/dom.js'
import { formatDate, statusLabel } from '../../core/format.js'
import { state } from '../../core/state.js'
import { setAction } from '../../ui/feedback.js'
import { activeCategory, activeKnowledgeView, categoryTree, filterKnowledgeDocuments, openCategoryEditor, setActiveCategory, setActiveKnowledgeView, systemViewRows, toggleCategory } from './categories.js'
import { indexSummary, openDocument, purposeLabel } from './documents.js'
import { openKnowledgeUpload } from './upload.js'

const content = $('#content')

export function renderKnowledge(renderPage) {
  setAction('+ 上传文档', () => openKnowledgeUpload(renderPage))
  const documents = filterKnowledgeDocuments(state.documents)
  const views = systemViewRows()
  const heading = state.categories.find(item => item.id === activeCategory)?.name || views.find(item => item.id === activeKnowledgeView).label
  content.innerHTML = `<div class="knowledge-layout">
    <aside class="category-panel">
      <div class="panel-heading"><b id="knowledge-system-heading">系统视图</b></div>
      <div class="knowledge-system-views" role="group" aria-labelledby="knowledge-system-heading">${views.map(view => `<button type="button" class="knowledge-system-view ${!activeCategory && activeKnowledgeView === view.id ? 'active' : ''}" data-knowledge-view="${view.id}" aria-pressed="${!activeCategory && activeKnowledgeView === view.id}"><span>${view.label}</span><small>${view.count}</small></button>`).join('')}</div>
      <div class="panel-heading knowledge-directory-heading"><div><b>知识目录</b><small>可自定义层级</small></div><button id="add-category" class="button small">+ 目录</button></div>
      <div class="category-tree">${categoryTree() || '<p class="muted category-empty">还没有目录</p>'}</div>
    </aside>
    <section class="document-panel">
      <div class="section-heading"><div><h2>${escapeHtml(heading)}</h2><p>${activeCategory ? '包含当前目录及所有子目录中的文档' : '按文档用途分别建立模板目录索引和正文分块索引'}</p></div><span class="record-count">${documents.length} 份文档</span></div>
      <div class="document-list-scroll">${documents.length ? `<table class="data-table"><thead><tr><th>文档</th><th>用途 / 模板属性</th><th>状态</th><th>索引</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${documents.map(item => `<tr class="document-row" data-id="${item.id}">
        <td><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.originalName)}</small></td>
        <td><span class="tag">${escapeHtml(item.purposeName || purposeLabel(item.purposeId))}</span>${item.isGenerationTemplate ? `<small>${escapeHtml(item.templateFamily)} · ${escapeHtml(item.templateVariant || '默认')} · ${escapeHtml(item.version || '无版本')}</small>` : `<small>${escapeHtml(item.documentType || '未分类文档')}</small>`}</td>
        <td><span class="tag ${item.status}">${statusLabel(item.status)}</span></td>
        <td>${indexSummary(item)}</td>
        <td>${formatDate(item.updatedAt)}</td><td><button class="button small view-document" data-id="${item.id}">查看</button></td></tr>`).join('')}</tbody></table>` : `<div class="empty">这个${activeCategory ? '目录' : '视图'}还没有文档</div>`}</div>
    </section>
  </div>`
  $('#add-category').onclick = () => openCategoryEditor(undefined, renderPage)
  $$('[data-knowledge-view]').forEach(button => button.onclick = () => {
    setActiveKnowledgeView(button.dataset.knowledgeView)
    renderKnowledge(renderPage)
    $(`[data-knowledge-view="${activeKnowledgeView}"]`).focus()
  })
  $$('.category-select').forEach(button => button.onclick = () => { setActiveCategory(button.dataset.id); renderKnowledge(renderPage) })
  $$('.category-toggle:not(:disabled)').forEach(button => button.onclick = () => { toggleCategory(button.dataset.id); renderKnowledge(renderPage) })
  $$('.category-edit').forEach(button => button.onclick = () => openCategoryEditor(state.categories.find(item => item.id === button.dataset.id), renderPage))
  $$('.view-document').forEach(button => button.onclick = () => openDocument(state.documents.find(item => item.id === button.dataset.id), renderPage))
}
