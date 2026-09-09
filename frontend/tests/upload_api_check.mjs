import assert from 'node:assert/strict'
import { createDom } from './helpers/dom.mjs'

const dom = await createDom({
  state: {
    processes: [], categories: [], purposes: [], documents: [], skills: [],
    settings: { chunking: {} }, services: {},
  },
})
const requests = []
dom.window.fetch = globalThis.fetch = async (url, options = {}) => {
  requests.push({ url: String(url), method: options.method || 'GET', body: options.body })
  return { ok: true, json: async () => ({}) }
}

const { previewKnowledge, analyzeKnowledge, rechunkKnowledge, indexKnowledge, deleteKnowledgePreview } = await import('../js/features/knowledge/upload-api.js')

// Catches an unencoded preview ID or an accidental default directory-suggestion query.
await analyzeKnowledge('preview/一')
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/analyze')

// Catches a lost opt-in query when the batch flow asks for a directory suggestion.
await analyzeKnowledge('preview/一', { suggestCategory: true })
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/analyze?suggestCategory=true')

// Catches a regression in the file's Base64 conversion or preview request shape.
const file = new dom.window.File(['ABC'], '合同.docx', { type: 'application/test' })
await previewKnowledge(file)
assert.deepEqual(JSON.parse(requests.at(-1).body), {
  fileName: '合同.docx', mimeType: 'application/test', fileBase64: 'QUJD',
})

// Catches a rechunk request that drops either its encoded path or settings body.
await rechunkKnowledge('preview/一', { mode: 'structure' })
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/rechunk')
assert.deepEqual(JSON.parse(requests.at(-1).body), { mode: 'structure' })

// Catches leaking the transport-only preview ID into the final indexing payload.
await indexKnowledge('preview/一', { title: '合同' })
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/index')
assert.deepEqual(JSON.parse(requests.at(-1).body), { title: '合同' })

// Catches deletion targeting an unencoded temporary-preview ID.
await deleteKnowledgePreview('preview/一')
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80')
assert.equal(requests.at(-1).method, 'DELETE')

console.log('upload_api_check: ok')
