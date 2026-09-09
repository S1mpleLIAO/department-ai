import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const chunking = { mode: 'structure', delimiter: '\n\n', maxTokens: 4000, overlapTokens: 80, parentMaxTokens: 1500, childMaxTokens: 300, childOverlapTokens: 30, cleanWhitespace: true, removeUrlsEmails: false }
const state = {
  processes: [], documents: [], skills: [], services: {}, settings: { chunking },
  categories: [{ id: 'contracts', name: '合同', parentId: null }, { id: 'guides', name: '指南', parentId: null }],
  purposes: [
    { id: 'template', name: '生成模板', canGenerateTemplate: true, chunkBody: false, inheritChunking: true, chunkSettings: {}, documentCount: 0 },
    { id: 'reference', name: '参考知识', canGenerateTemplate: false, chunkBody: true, inheritChunking: true, chunkSettings: {}, documentCount: 0 },
  ],
}
const dom = await createDom({ hash: 'knowledge', state })
const { setActiveCategory } = await import('../js/features/knowledge/categories.js')
const requests = []
const previews = new Map()
const aiFailures = new Set()
const indexFailures = new Set()
const deleteFailures = new Set()
const parseFailures = new Set()
const rechunkFailures = new Set()
const holds = new Map()
let sequence = 0
let indexActive = 0
let maxIndexActive = 0
const response = (payload, ok = true) => ({ ok, json: async () => structuredClone(payload) })
globalThis.fetch = dom.window.fetch = async (url, options = {}) => {
  const body = options.body && JSON.parse(options.body)
  const method = options.method || 'GET'
  requests.push({ url, method, body })
  if (url === '/api/state') return response(state)
  if (url === '/api/categories') {
    const category = { id: 'new-category', ...body }
    state.categories.push(category)
    return response({ category })
  }
  if (url === '/api/knowledge/preview') {
    if (parseFailures.has(body.fileName)) return response({ detail: '无法解析该文件' }, false)
    const id = `preview/${++sequence}`
    previews.set(id, body.fileName)
    await holds.get(body.fileName)
    return response({ id, fileName: body.fileName, characters: 3 })
  }
  const id = decodeURIComponent(url.split('/')[4])
  const name = previews.get(id)
  if (url.includes('/analyze')) return aiFailures.has(name)
    ? response({ detail: 'AI 服务暂不可用' }, false)
    : response({ id, metadata: { title: name.replace('.docx', ''), suggestedPurposeId: 'template', suggestedCategoryId: 'guides', templateFamily: '合同', outline: ['正文'] } })
  if (url.endsWith('/rechunk')) return rechunkFailures.has(name) ? response({ detail: '分块服务暂不可用' }, false) : response({ id, characters: 3, chunks: body.mode === 'parent-child'
    ? [{ index: 0, parentIndex: null, sectionPath: '正文', content: 'ABC', tokenCount: 3, enabled: false }, { index: 1, parentIndex: 0, sectionPath: '正文', content: 'ABC', tokenCount: 3, enabled: true }]
    : [{ index: 0, parentIndex: null, sectionPath: '正文', content: 'ABC', tokenCount: 3, enabled: true }] })
  if (url.endsWith('/index')) {
    indexActive += 1
    maxIndexActive = Math.max(maxIndexActive, indexActive)
    await new Promise(resolve => setTimeout(resolve, 15))
    indexActive -= 1
    return indexFailures.has(name) ? response({ detail: '索引服务暂不可用' }, false) : response({ saved: true })
  }
  if (method === 'DELETE') return response({ deleted: true, detail: '临时文件清理失败' }, !deleteFailures.has(name))
  throw new Error(`Unexpected request: ${method} ${url}`)
}
async function waitFor(predicate, message = '批量上传状态未到达预期') {
  for (let i = 0; i < 160; i += 1) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  assert.fail(message)
}
function attachFiles(names) {
  const input = document.querySelector('#knowledge-file')
  Object.defineProperty(input, 'files', { configurable: true, value: names.map(name => new dom.window.File(['ABC'], name)) })
  input.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
}
const rows = () => [...document.querySelectorAll('.batch-upload-row')]
const row = name => rows().find(node => node.textContent.includes(name))
const status = name => row(name)?.querySelector('.batch-upload-status').textContent
const change = (control, value) => { control.value = value; control.dispatchEvent(new dom.window.Event('change', { bubbles: true })) }
async function closeBatch() {
  document.querySelector('#batch-close').click()
  await waitFor(() => !document.querySelector('#editor-dialog').open)
}

setActiveCategory('contracts')
document.querySelector('#page-action').click()
attachFiles(['合同A.docx', '合同B.docx'])
document.querySelector('#parse-document').click()
await waitFor(() => document.querySelectorAll('.batch-upload-row').length === 2, '多个文件必须进入批量审核，不得丢弃第二份文件')
await waitFor(() => rows().every(node => node.textContent.includes('可入库')))
assert.ok(requests.filter(item => item.url.includes('/analyze')).every(item => !item.url.includes('suggestCategory=true')), '目录入口不得请求 AI 改派目录')
assert.ok([...document.querySelectorAll('[data-batch-category]')].every(select => select.value === 'contracts'), '目录入口必须保留两份文件的明确目录')
assert.equal(document.querySelector('#knowledge-file'), null, '批量审核必须替换单文件步骤')
await closeBatch()
for (const id of ['preview/1', 'preview/2']) assert.equal(requests.filter(item => item.method === 'DELETE' && item.url.endsWith(encodeURIComponent(id))).length, 1, '关闭应清理每个未入库预览一次')

requests.length = 0
aiFailures.add('待确认.docx')
indexFailures.add('失败.docx')
setActiveCategory('')
document.querySelector('#page-action').click()
attachFiles(['成功.docx', '失败.docx', '待确认.docx', '保留.docx'])
document.querySelector('#parse-document').click()
await waitFor(() => rows().length === 4 && status('待确认.docx') === '需要确认' && status('保留.docx') === '可入库')
assert.ok(requests.filter(item => item.url.includes('/analyze')).every(item => item.url.includes('?suggestCategory=true')), '首页入口必须启用目录建议')
assert.equal(row('成功.docx').querySelector('[data-batch-category]').value, 'guides', '有效 AI 目录建议必须反映到列表')
assert.equal(row('待确认.docx').querySelector('[data-batch-select]').checked, false, 'AI 失败不得自动勾选')
assert.match(row('待确认.docx').textContent, /重试分析/, 'AI 失败必须提供原阶段重试')
assert.match(row('待确认.docx').textContent, /正文已解析/, 'AI 失败应保留已解析正文')
assert.equal(rows()[0], row('待确认.docx'), '异常行应先于可入库行显示')
assert.equal(document.querySelector('.batch-upload-summary').getAttribute('aria-live'), 'polite', '汇总变化应可被读屏感知')
assert.equal(row('成功.docx').querySelector('[data-batch-select]').checked, true, '有效行默认参与确认')
const retained = row('保留.docx').querySelector('[data-batch-select]')
retained.checked = false
retained.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
document.querySelector('#batch-confirm').click()
document.querySelector('#batch-confirm').click()
await waitFor(() => status('成功.docx') === '已入库' && status('失败.docx') === '失败')
assert.deepEqual(requests.filter(item => item.url.endsWith('/index')).map(item => item.body.title), ['成功', '失败'], '入库必须只提交已勾选且可入库的行')
assert.equal(maxIndexActive, 1, '最终提交不得并发索引')
assert.ok(row('成功.docx').querySelector('[data-batch-select]').disabled, '已完成行必须锁定，防止重复索引')
assert.match(row('失败.docx').textContent, /重试入库/, '部分失败应保留入库重试入口')
assert.equal(document.querySelector('#editor-dialog').open, true, '部分成功不能自动关闭审核')

row('保留.docx').querySelector('[data-batch-detail]').click()
change(document.querySelector('#document-purpose'), 'reference')
document.querySelector('#upload-category-create').click()
document.querySelector('#upload-category-name').value = '新目录'
change(document.querySelector('#upload-category-parent'), 'contracts')
document.querySelector('#upload-category-save').click()
await waitFor(() => document.querySelector('#document-category').value === 'new-category')
assert.deepEqual(requests.find(item => item.url === '/api/categories').body, { name: '新目录', parentId: 'contracts' }, '内联创建必须发送名称和父目录')
assert.equal(document.activeElement, document.querySelector('#document-category'), '新目录创建后焦点应返回目录选择')
document.querySelector('#batch-detail-save').click()
await waitFor(() => document.querySelector('.batch-upload-detail').hidden)
assert.equal(requests.filter(item => item.url.endsWith('/rechunk')).length, 1, '用途从模板改为参考必须重新分块')
assert.equal(row('保留.docx').querySelector('[data-batch-category]').value, 'new-category', '详情保存后列表必须保留新目录')
assert.equal(status('成功.docx'), '已入库', '编辑另一份详情不得重置已完成行')
assert.equal(document.activeElement, row('保留.docx').querySelector('[data-batch-detail]'), '关闭详情必须恢复来源行焦点')

deleteFailures.add('待确认.docx')
row('待确认.docx').querySelector('[data-batch-remove]').click()
await waitFor(() => row('待确认.docx')?.textContent.includes('清理失败'))
assert.equal(rows().length, 4, '清理失败不得移除行并遗留预览')
deleteFailures.clear()
indexFailures.clear()
row('失败.docx').querySelector('[data-batch-retry]').click()
await waitFor(() => status('失败.docx') === '已入库')
assert.equal(requests.filter(item => item.url === '/api/knowledge/preview').length, 4, '入库重试不得重新上传文件')
assert.equal(requests.filter(item => item.url.includes('/analyze')).length, 4, '入库重试不得重新分析')
aiFailures.clear()
row('待确认.docx').querySelector('[data-batch-retry]').click()
await waitFor(() => status('待确认.docx') === '可入库')
assert.equal(requests.filter(item => item.url === '/api/knowledge/preview').length, 4, 'AI 重试必须复用已解析的预览')
const beforeClose = requests.length
await closeBatch()
const deletedOnClose = requests.slice(beforeClose).filter(item => item.method === 'DELETE').map(item => decodeURIComponent(item.url.split('/').at(-1))).sort()
assert.deepEqual(deletedOnClose, ['preview/5', 'preview/6'], '关闭仅清理未入库预览，每份恰好一次')

parseFailures.add('无法解析.docx')
aiFailures.clear()
document.querySelector('#page-action').click()
attachFiles(['无法解析.docx', '正常.docx'])
document.querySelector('#parse-document').click()
await waitFor(() => status('无法解析.docx') === '失败' && status('正常.docx') === '可入库')
assert.equal(row('无法解析.docx').querySelector('[data-batch-select]').disabled, true, '没有正文预览的解析失败行不得被批量用途操作提升为可入库')
assert.equal(row('无法解析.docx').querySelector('[data-batch-remove]').disabled, false, '解析失败仍应可移除')
parseFailures.clear()
row('无法解析.docx').querySelector('[data-batch-retry]').click()
await waitFor(() => status('无法解析.docx') === '可入库')
change(document.querySelector('#batch-category'), '')
document.querySelector('#batch-apply-category').click()
assert.ok([...document.querySelectorAll('[data-batch-category]')].every(control => control.value === ''), '批量设置目录必须允许未分类')
change(document.querySelector('#batch-purpose'), 'reference')
document.querySelector('#batch-apply-purpose').click()
assert.ok(rows().every(node => node.querySelector('.batch-upload-status').textContent === '需要确认'), '批量用途改变必须使旧分块失效')
assert.ok(rows().every(node => !node.querySelector('[data-batch-select]').checked), '分块失效后必须取消自动入库选择')
rechunkFailures.add('正常.docx')
row('正常.docx').querySelector('[data-batch-retry]').click()
await waitFor(() => row('正常.docx').textContent.includes('分块失败'))
const parseCount = requests.filter(item => item.url === '/api/knowledge/preview').length
rechunkFailures.clear()
row('正常.docx').querySelector('[data-batch-retry]').click()
await waitFor(() => status('正常.docx') === '可入库')
assert.equal(requests.filter(item => item.url === '/api/knowledge/preview').length, parseCount, '分块重试不得重新解析正文')
row('正常.docx').querySelector('[data-batch-detail]').click()
change(document.querySelector('#chunk-mode'), 'parent-child')
document.querySelector('#batch-detail-save').click()
await waitFor(() => document.querySelector('.batch-upload-detail').hidden)
row('正常.docx').querySelector('[data-batch-detail]').click()
assert.equal(document.querySelector('#chunk-mode').value, 'parent-child', '再次打开详情必须保留已确认的分块模式')
const parentCheckbox = document.querySelector('.chunk-enabled')
assert.equal(parentCheckbox.disabled, true, '父子分块的父块不可直接加入检索选择')
document.querySelector('#parent-max').value = '1600'
rechunkFailures.add('正常.docx')
document.querySelector('#batch-detail-save').click()
await waitFor(() => document.querySelector('#batch-detail-error').textContent.includes('分块失败'))
assert.equal(parentCheckbox.disabled, true, '详情分块失败恢复控件时，不得启用只读父块')
assert.equal(document.querySelector('#parent-max').value, '1600', '分块失败须保留自定义设置输入')
rechunkFailures.clear()
document.querySelector('#batch-detail-save').click()
await waitFor(() => document.querySelector('.batch-upload-detail').hidden)
change(document.querySelector('#batch-filter'), 'failed')
assert.equal(rows().length, 0, '筛选无结果时不得展示不匹配的文件')
assert.match(document.querySelector('.batch-upload-list').textContent, /没有符合筛选条件/, '筛选无结果须提供明确提示')
change(document.querySelector('#batch-filter'), 'all')
assert.equal(row('正常.docx').querySelector('[data-batch-select]').checked, true, '筛选往返必须保留批次选择')
change(document.querySelector('#batch-filter'), 'needs-review')
row('无法解析.docx').querySelector('[data-batch-detail]').click()
document.querySelector('#batch-detail-save').click()
await waitFor(() => document.querySelector('.batch-upload-detail').hidden)
assert.equal(document.activeElement, document.querySelector('#batch-filter'), '详情保存后原行被筛选隐藏时，应把焦点返回筛选控件')
await closeBatch()

let releasePreview
holds.set('缓慢A.docx', new Promise(resolve => { releasePreview = resolve }))
holds.set('缓慢B.docx', holds.get('缓慢A.docx'))
const beforeSlow = requests.length
document.querySelector('#page-action').click()
attachFiles(['缓慢A.docx', '缓慢B.docx', '排队.docx'])
document.querySelector('#parse-document').click()
await waitFor(() => requests.slice(beforeSlow).filter(item => item.url === '/api/knowledge/preview').length === 2)
assert.equal(status('排队.docx'), '等待解析', '准备池只能同时处理两份文件')
assert.ok(row('缓慢A.docx').querySelector('[data-batch-remove]').disabled, '解析期间不能移除正在使用的预览')
document.querySelector('#editor-dialog').dispatchEvent(new dom.window.Event('cancel', { cancelable: true }))
await waitFor(() => document.querySelector('#confirm-dialog').open)
assert.equal(document.querySelector('#editor-dialog').open, true, '处理中关闭必须等待产品确认')
document.querySelector('#confirm-dialog button[value="cancel"]').click()
await waitFor(() => !document.querySelector('#confirm-dialog').open)
assert.equal(document.querySelector('#editor-dialog').open, true, '取消关闭确认应保留批次')
document.querySelector('#batch-close').click()
await waitFor(() => document.querySelector('#confirm-dialog').open)
document.querySelector('#confirm-dialog button[value="confirm"]').click()
await waitFor(() => !document.querySelector('#editor-dialog').open)
const oldSummary = document.querySelector('.batch-upload-summary').textContent
releasePreview()
await waitFor(() => requests.slice(beforeSlow).filter(item => item.method === 'DELETE').length === 2)
assert.equal(requests.slice(beforeSlow).filter(item => item.url === '/api/knowledge/preview').length, 2, '关闭后不能继续解析排队文件')
assert.equal(requests.slice(beforeSlow).filter(item => item.url.includes('/analyze')).length, 0, '关闭后迟到的正文响应不得继续分析')
assert.equal(document.querySelector('.batch-upload-summary').textContent, oldSummary, '关闭后的迟到响应不得改写 DOM')
console.log('batch-upload-check: ok')
