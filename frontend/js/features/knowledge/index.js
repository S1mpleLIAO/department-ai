import { $, $$, escapeHtml } from '../../core/dom.js'
import { formatDate, statusLabel } from '../../core/format.js'
import { state } from '../../core/state.js'
import { setAction } from '../../ui/feedback.js'
import { activeCategory, categoryTree, openCategoryEditor, setActiveCategory, toggleCategory } from './categories.js'
import { indexSummary, openDocument, purposeLabel } from './documents.js'
import { openKnowledgeUpload } from './upload.js'

const content = $('#content')

export function renderKnowledge(renderPage) {
  setAction('+ 上传文档', () => openKnowledgeUpload(renderPage))
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
  $('#add-category').onclick = () => openCategoryEditor(undefined, renderPage)
  $('#all-category').onclick = () => { setActiveCategory(''); renderKnowledge(renderPage) }
  $$('.category-select').forEach(button => button.onclick = () => { setActiveCategory(button.dataset.id); renderKnowledge(renderPage) })
  $$('.category-toggle:not(:disabled)').forEach(button => button.onclick = () => { toggleCategory(button.dataset.id); renderKnowledge(renderPage) })
  $$('.category-edit').forEach(button => button.onclick = () => openCategoryEditor(state.categories.find(item => item.id === button.dataset.id), renderPage))
  $$('.view-document').forEach(button => button.onclick = () => openDocument(state.documents.find(item => item.id === button.dataset.id), renderPage))
}
