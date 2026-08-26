import { $, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction, openDialog } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'

export let activeCategory = ''
const collapsedCategories = new Set()

export function setActiveCategory(value) { activeCategory = value }

export function toggleCategory(id) {
  if (collapsedCategories.has(id)) collapsedCategories.delete(id)
  else collapsedCategories.add(id)
}

async function refreshCategories(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

export function categoryOptions(selected = '', exclude = '') {
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

export function categoryTree() {
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

export function openCategoryEditor(category, renderPage) {
  const current = category || { parentId: activeCategory || '', name: '' }
  const currentDialog = openDialog(category ? '编辑知识目录' : '新建知识目录', '目录可以随时新增、重命名和移动', `
    <div class="form-grid">
      <div class="field full"><label>目录名称</label><input id="category-name" value="${escapeHtml(current.name)}" placeholder="网络"></div>
      <div class="field"><label>上级目录</label><select id="category-parent"><option value="">根目录</option>${categoryOptions(current.parentId || '', current.id)}</select></div>
      <p class="muted small-copy">新目录会自动排在同级目录末尾；移动目录时，下面的子目录和文档会一起保留。</p>
    </div>
    ${category ? '<div class="danger-zone"><b>删除目录</b><span>只有没有子目录和文档时才能删除。</span><button type="button" id="delete-category" class="button danger">删除</button></div>' : ''}`, async () => {
      const create = !category
      const body = { name: $('#category-name').value.trim(), parentId: $('#category-parent').value || null }
      const path = create ? '/api/categories' : `/api/categories/${encodeURIComponent(category.id)}`
      const result = await request(path, { method: create ? 'POST' : 'PUT', body })
      activeCategory = result.category.id
    }, { afterSave: () => refreshCategories(renderPage) })
  if (category) $('#delete-category').onclick = async () => {
    if (!await confirmAction('确定删除这个目录吗？', '只有空目录可以删除。')) return
    try {
      await request(`/api/categories/${encodeURIComponent(category.id)}`, { method: 'DELETE' })
      await currentDialog.close()
      activeCategory = ''
      await refreshCategories(renderPage)
      toast('目录已删除')
    } catch (error) { toast(error.message, true) }
  }
}
