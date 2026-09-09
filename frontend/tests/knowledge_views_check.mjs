import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const documents = [
  { id: 'unclassified', categoryId: null, status: 'effective' },
  { id: 'draft', categoryId: 'child', status: 'draft' },
  { id: 'published', categoryId: 'root', status: 'effective' },
  { id: 'obsolete', categoryId: 'other', status: 'obsolete' },
].map(item => ({
  title: item.id, originalName: `${item.id}.txt`, purposeId: 'reference', purposeName: '参考知识',
  documentType: '说明', isGenerationTemplate: false, indexed: false, documentIndexed: false,
  chunkIndexed: false, chunkCount: 0, updatedAt: '2026-09-09T00:00:00Z', ...item,
}))
const state = {
  processes: [], skills: [], services: {},
  categories: [
    { id: 'root', name: '业务知识', parentId: null },
    { id: 'child', name: '子目录', parentId: 'root' },
    { id: 'other', name: '其他', parentId: null },
  ],
  purposes: [{ id: 'reference', name: '参考知识', canGenerateTemplate: false, chunkBody: true, inheritChunking: true, chunkSettings: {} }],
  settings: { chunking: {
    mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80,
    parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30,
    cleanWhitespace: true, removeUrlsEmails: false,
  } },
  documents,
}
const dom = await createDom({ hash: 'knowledge', state })
const categories = await import('../js/features/knowledge/categories.js')
const { renderKnowledge } = await import('../js/features/knowledge/index.js')
const { replaceState } = await import('../js/core/state.js')
const $ = selector => dom.window.document.querySelector(selector)
const rows = () => [...dom.window.document.querySelectorAll('.document-row')].map(row => row.dataset.id)
const expectedViews = [
  { id: 'all', label: '全部文档', count: 4 },
  { id: 'unclassified', label: '待整理', count: 1 },
  { id: 'draft', label: '草稿', count: 1 },
  { id: 'published', label: '已发布', count: 2 },
  { id: 'obsolete', label: '已废止', count: 1 },
]

assert.equal(typeof categories.setActiveKnowledgeView, 'function', '系统视图应支持独立选择')
assert.equal(categories.activeKnowledgeView, 'all')
assert.deepEqual(categories.systemViewRows(), expectedViews)
assert.deepEqual(categories.systemViewRows([]).map(row => row.count), [0, 0, 0, 0, 0])
for (const [view, expected] of [
  ['unclassified', ['unclassified']], ['draft', ['draft']],
  ['published', ['unclassified', 'published']], ['obsolete', ['obsolete']],
  ['all', ['unclassified', 'draft', 'published', 'obsolete']],
]) {
  categories.setActiveCategory('root')
  categories.setActiveKnowledgeView(view)
  assert.equal(categories.activeCategory, '', '每个系统视图都应清除真实目录选择')
  assert.deepEqual(categories.filterKnowledgeDocuments(documents).map(item => item.id), expected)
}
categories.setActiveKnowledgeView('unclassified')
assert.deepEqual(categories.filterKnowledgeDocuments([
  { id: 'empty', categoryId: '', status: 'draft' },
  { id: 'null', categoryId: null, status: 'obsolete' },
]).map(item => item.id), ['empty', 'null'], '待整理不应限制发布状态')
categories.setActiveCategory('root')
assert.equal(categories.activeKnowledgeView, 'all')
assert.deepEqual(categories.filterKnowledgeDocuments(documents).map(item => item.id), ['draft', 'published'], '目录应包含子目录且不残留系统筛选')
for (const invalid of ['unknown', 'toString', '__proto__', null]) {
  assert.throws(() => categories.setActiveKnowledgeView(invalid), /视图/)
  assert.equal(categories.activeCategory, 'root', '无效视图不得破坏当前导航状态')
}

categories.setActiveKnowledgeView('all')
renderKnowledge(() => {})
assert.deepEqual([...dom.window.document.querySelectorAll('[data-knowledge-view]')].map(button => ({
  id: button.dataset.knowledgeView, label: button.querySelector('span').textContent,
  count: Number(button.querySelector('small').textContent),
})), expectedViews)
assert.equal($('.knowledge-system-views #add-category'), null)
assert.ok($('.knowledge-directory-heading #add-category'), '新增目录操作只属于真实目录分组')
assert.equal($('.category-tree [data-knowledge-view]'), null)
assert.ok($('.category-panel').textContent.indexOf('系统视图') < $('.category-panel').textContent.indexOf('知识目录'))
for (const [view, expected] of [['unclassified', ['unclassified']], ['draft', ['draft']], ['published', ['unclassified', 'published']], ['obsolete', ['obsolete']]]) {
  $(`[data-knowledge-view="${view}"]`).click()
  assert.deepEqual(rows(), expected)
  assert.equal($('.section-heading h2').textContent, expectedViews.find(item => item.id === view).label)
  assert.equal($('.record-count').textContent, `${expected.length} 份文档`)
  assert.equal($(`[data-knowledge-view="${view}"]`).getAttribute('aria-pressed'), 'true')
  assert.equal(dom.window.document.activeElement, $(`[data-knowledge-view="${view}"]`), '重绘后保留系统按钮键盘焦点')
}
$('.category-select[data-id="root"]').click()
assert.equal(categories.activeKnowledgeView, 'all')
assert.deepEqual(rows(), ['draft', 'published'])
assert.equal($('.section-heading h2').textContent, '业务知识')
assert.equal($('[data-knowledge-view][aria-pressed="true"]'), null, '选择目录时不高亮全部文档')
$('#page-action').click()
assert.equal($('#document-category').value, 'root', '目录内上传继续继承入口目录')
$('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))
$('[data-knowledge-view="unclassified"]').click()
$('#page-action').click()
assert.equal($('#document-category').value, '', '系统视图上传以空目录开始')
assert.deepEqual([...$('#document-category').options].map(option => option.value), ['', 'root', 'child', 'other'], '系统视图不应出现在真实目录选择器中')
$('#editor-dialog .dialog-close').click()
await new Promise(resolve => setTimeout(resolve, 220))

// Creating a real directory from a system view must also reset the filter.
const saved = { id: 'created', name: '新目录', parentId: null }
globalThis.fetch = dom.window.fetch = async url => ({ ok: true, json: async () => String(url) === '/api/categories'
  ? { category: saved } : { ...state, categories: [...state.categories, saved] } })
$('#add-category').click()
$('#category-name').value = saved.name
$('#dialog-save').click()
await new Promise(resolve => setTimeout(resolve, 220))
assert.equal(categories.activeCategory, 'created')
assert.equal(categories.activeKnowledgeView, 'all', '创建目录后应进入真实目录视图')

replaceState({ ...state, documents: [] })
categories.setActiveKnowledgeView('draft')
renderKnowledge(() => {})
assert.equal($('.record-count').textContent, '0 份文档')
assert.equal($('.empty').textContent, '这个视图还没有文档')
assert.equal(dom.window.document.querySelectorAll('[data-knowledge-view]').length, 5)
dom.window.close()
console.log('knowledge-views-check: ok')
