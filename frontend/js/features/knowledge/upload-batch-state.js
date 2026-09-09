export const BATCH_PREPARE_CONCURRENCY = 2

export function createBatchItems(files, entryCategoryId, idFactory = () => crypto.randomUUID()) {
  return files.map((file, index) => {
    const id = idFactory(index)
    return {
      id,
      file,
      entryCategoryId,
      preview: null,
      metadata: {
        id,
        title: file.name.replace(/\.[^.]+$/, ''),
        purposeId: '',
        documentType: '',
        keywords: [],
        outline: [],
        categoryId: entryCategoryId,
        status: 'effective',
        summary: '',
        templateFamily: '',
        templateVariant: '',
        version: 'V1.0',
        applicableScenario: '',
      },
      chunks: [],
      status: 'waiting',
      error: '',
      retryAction: '',
      selected: false,
    }
  })
}

function hasValue(value) {
  return Array.isArray(value) ? value.length > 0 : String(value ?? '').trim().length > 0
}

export function mergeSuggestion(item, suggestion, purposes, categories) {
  for (const field of ['title', 'documentType', 'keywords', 'outline', 'summary', 'templateFamily', 'templateVariant', 'version', 'applicableScenario']) {
    if (hasValue(suggestion[field])) item.metadata[field] = suggestion[field]
  }
  if (hasValue(suggestion.suggestedPurposeId) && purposes.some(purpose => purpose.id === suggestion.suggestedPurposeId)) {
    item.metadata.purposeId = suggestion.suggestedPurposeId
  }
  if (!item.entryCategoryId && hasValue(suggestion.suggestedCategoryId) && categories.some(category => category.id === suggestion.suggestedCategoryId)) {
    item.metadata.categoryId = suggestion.suggestedCategoryId
  }
  return item
}

function review(item, error) {
  item.status = 'needs-review'
  item.error = error
  item.selected = false
  return item
}

export function evaluateBatchItem(item, purposes) {
  if (!item.preview) return review(item, '请先解析正文')
  const purpose = purposes.find(candidate => candidate.id === item.metadata.purposeId)
  const enabledChunks = item.chunks.filter(chunk => chunk.enabled)
  if (!item.metadata.title.trim()) return review(item, '请确认文档标题')
  if (!purpose) return review(item, '请确认文档用途')
  if (purpose.canGenerateTemplate && !item.metadata.templateFamily.trim()) return review(item, '请填写模板家族')
  if (purpose.chunkBody && enabledChunks.length === 0) return review(item, '至少保留一个有效正文分块')
  if (item.chunks.some(chunk => !chunk.content?.trim())) return review(item, '分块正文不能为空')
  item.status = 'ready'
  item.error = ''
  item.retryAction = ''
  item.selected = true
  return item
}

export async function runBatchPool(items, worker, concurrency = BATCH_PREPARE_CONCURRENCY) {
  const queue = [...items]
  let cursor = 0
  async function next() {
    while (cursor < queue.length) {
      const item = queue[cursor]
      cursor += 1
      try {
        await worker(item)
      } catch (error) {
        item.status = 'failed'
        item.error = error instanceof Error ? error.message : String(error)
        item.retryAction ||= 'prepare'
        item.selected = false
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, next))
}
