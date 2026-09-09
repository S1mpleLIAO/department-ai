import { request } from '../../core/http.js'

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

export async function previewKnowledge(file) {
  return request('/api/knowledge/preview', {
    method: 'POST',
    body: {
      fileName: file.name,
      mimeType: file.type || 'application/octet-stream',
      fileBase64: await fileToBase64(file),
    },
  })
}

export function analyzeKnowledge(previewId, { suggestCategory = false } = {}) {
  const suffix = suggestCategory ? '?suggestCategory=true' : ''
  return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/analyze${suffix}`, { method: 'POST' })
}

export function rechunkKnowledge(previewId, settings) {
  return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/rechunk`, { method: 'POST', body: settings })
}

export function indexKnowledge(previewId, data) {
  if (data.chunks?.some(chunk => !chunk.content?.trim())) throw new Error('分块正文不能为空')
  const body = { ...data }
  if (body.categoryId === '') body.categoryId = null
  delete body.previewId
  return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/index`, { method: 'POST', body })
}

export function deleteKnowledgePreview(previewId) {
  return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}`, { method: 'DELETE' })
}
