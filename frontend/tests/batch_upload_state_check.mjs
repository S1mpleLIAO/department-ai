import assert from 'node:assert/strict'
import {
  BATCH_PREPARE_CONCURRENCY,
  createBatchItems,
  evaluateBatchItem,
  mergeSuggestion,
  runBatchPool,
} from '../js/features/knowledge/upload-batch-state.js'

const files = [
  { name: '合同甲.docx' },
  { name: '合同乙.pdf' },
  { name: '合同丙.txt' },
]
const purposes = [
  { id: 'reference-knowledge', canGenerateTemplate: false, chunkBody: true },
  { id: 'generation-template', canGenerateTemplate: true, chunkBody: false },
]
const categories = [{ id: 'contracts' }, { id: 'manual' }]

const items = createBatchItems(files, 'contracts', index => `knowledge-test-${index}`)
assert.deepEqual(items.map(item => item.metadata.categoryId), ['contracts', 'contracts', 'contracts'])
assert.deepEqual(items.map(item => item.status), ['waiting', 'waiting', 'waiting'])
assert.deepEqual(items[0], {
  id: 'knowledge-test-0', file: files[0], entryCategoryId: 'contracts', preview: null,
  metadata: {
    id: 'knowledge-test-0', title: '合同甲', purposeId: '', documentType: '', keywords: [], outline: [],
    categoryId: 'contracts', status: 'effective', summary: '', templateFamily: '', templateVariant: '',
    version: 'V1.0', applicableScenario: '',
  },
  chunks: [], status: 'waiting', error: '', retryAction: '', selected: false,
})

const homepage = createBatchItems([files[0]], '', () => 'knowledge-home')[0]
mergeSuggestion(homepage, {
  title: 'AI 合同', suggestedPurposeId: 'reference-knowledge', suggestedCategoryId: 'contracts',
}, purposes, categories)
assert.equal(homepage.metadata.title, 'AI 合同')
assert.equal(homepage.metadata.purposeId, 'reference-knowledge')
assert.equal(homepage.metadata.categoryId, 'contracts')

const inside = createBatchItems([files[0]], 'manual', () => 'knowledge-inside')[0]
mergeSuggestion(inside, {
  title: 'AI 合同', suggestedPurposeId: 'reference-knowledge', suggestedCategoryId: 'contracts',
}, purposes, categories)
assert.equal(inside.metadata.categoryId, 'manual')
mergeSuggestion(inside, { suggestedPurposeId: 'missing-purpose', suggestedCategoryId: 'missing-category' }, purposes, categories)
assert.equal(inside.metadata.purposeId, 'reference-knowledge')
assert.equal(inside.metadata.categoryId, 'manual')

homepage.chunks = [{ enabled: true, content: '正文' }]
homepage.preview = { id: 'preview-homepage' }
homepage.error = '上一轮预览失败'
homepage.retryAction = 'reanalyze'
evaluateBatchItem(homepage, purposes)
assert.equal(homepage.status, 'ready')
assert.equal(homepage.selected, true)
assert.equal(homepage.error, '')
assert.equal(homepage.retryAction, '')

const template = createBatchItems([files[1]], '', () => 'knowledge-template')[0]
template.metadata.purposeId = 'generation-template'
template.preview = { id: 'preview-template' }
template.selected = true
evaluateBatchItem(template, purposes)
assert.equal(template.status, 'needs-review')
assert.equal(template.selected, false)
assert.equal(template.error, '请填写模板家族')

const emptyCategory = createBatchItems([files[2]], '', () => 'knowledge-empty-category')[0]
emptyCategory.metadata.purposeId = 'reference-knowledge'
emptyCategory.preview = { id: 'preview-empty-category' }
emptyCategory.chunks = [{ enabled: true, content: '正文' }]
evaluateBatchItem(emptyCategory, purposes)
assert.equal(emptyCategory.status, 'ready')
assert.equal(emptyCategory.selected, true)

const poolItems = createBatchItems(files, '', index => `knowledge-test-${index}`)
const started = []
let active = 0
let maximumActive = 0
let releaseGate
const gate = new Promise(resolve => { releaseGate = resolve })
await runBatchPool(poolItems, async item => {
  active += 1
  maximumActive = Math.max(maximumActive, active)
  started.push(item.id)
  try {
    if (started.length === 2) releaseGate()
    if (started.length <= 2) await gate
    if (item.id === 'knowledge-test-1') {
      item.retryAction = 'reanalyze'
      throw new Error('第二个文件准备失败')
    }
  } finally {
    active -= 1
  }
})
assert.equal(BATCH_PREPARE_CONCURRENCY, 2)
assert.equal(maximumActive, 2)
assert.deepEqual(started.sort(), ['knowledge-test-0', 'knowledge-test-1', 'knowledge-test-2'])
assert.equal(poolItems[1].status, 'failed')
assert.equal(poolItems[1].error, '第二个文件准备失败')
assert.equal(poolItems[1].retryAction, 'reanalyze')
assert.equal(poolItems[1].selected, false)


// Catches cursor drift when ready A is removed while B/C occupy both workers and D waits.
const mutableQueue = createBatchItems(['A', 'B', 'C', 'D'].map(name => ({ name })), '', index => String(index))
const visited = []
let releaseWaiting
const waitingGate = new Promise(resolve => { releaseWaiting = resolve })
let bothHeld
const held = new Promise(resolve => { bothHeld = resolve })
const queueRun = runBatchPool(mutableQueue, async item => {
  visited.push(item.file.name)
  if (item.file.name === 'B' || item.file.name === 'C') {
    if (visited.includes('B') && visited.includes('C')) bothHeld()
    await waitingGate
  }
  item.status = 'ready'
})
await held
assert.equal(mutableQueue[0].status, 'ready')
mutableQueue.splice(0, 1)
releaseWaiting()
await queueRun
assert.deepEqual(visited, ['A', 'B', 'C', 'D'], '移除已准备行不能跳过等待中的 D')

for (const enabled of [true, false]) {
  const blank = { ...emptyCategory, chunks: [{ content: '有效正文', enabled: true }, { content: ' \n\t ', enabled }] }
  evaluateBatchItem(blank, purposes)
  assert.equal(blank.status, 'needs-review', '所有将发送的块（包括未启用父块）必须 trim 后非空')
  assert.equal(blank.selected, false)
}
const previewless = { ...emptyCategory, preview: null }
evaluateBatchItem(previewless, purposes)
assert.equal(previewless.status, 'needs-review', '完整元数据和 chunks 也不能使无预览行获得入库资格')
assert.equal(previewless.selected, false)
console.log('batch-upload-state-check: ok')
