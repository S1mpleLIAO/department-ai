import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from '../../../deepseek-harness/node_modules/jsdom/lib/api.js'

const dom = new JSDOM(await readFile(new URL('../index.html', import.meta.url), 'utf8'))
Object.defineProperties(globalThis, {
  window: { configurable: true, value: dom.window },
  document: { configurable: true, value: dom.window.document },
})

const metadata = await import('../js/features/knowledge/upload-metadata.js')
const chunks = await import('../js/features/knowledge/upload-chunks.js')

for (const name of ['metadataFormHtml', 'applyMetadataSuggestion', 'collectMetadata', 'validateMetadata', 'selectedPurpose', 'togglePurposeFields']) {
  assert.equal(typeof metadata[name], 'function', `metadata module 应导出 ${name}`)
}
for (const name of ['chunkPanelHtml', 'renderChunkPreview', 'collectPreviewChunks', 'hasEnabledChunk', 'renderIndexPlan']) {
  assert.equal(typeof chunks[name], 'function', `chunks module 应导出 ${name}`)
}

const form = metadata.metadataFormHtml({
  documentId: 'knowledge-test',
  categoryOptionsHtml: '<option value="engineering">工程</option>',
  purposes: [{ id: 'reference-knowledge', name: '参考知识' }],
})
assert.match(form, /<select id="document-purpose"><option value="" selected>待确认<\/option>/, '用途选择应以待确认开始')
assert.doesNotMatch(form, /<option value="reference-knowledge" selected>/, '不得默认选择 reference-knowledge')

console.log('knowledge-upload-check: ok')
