import assert from 'node:assert/strict'
import { $, $$, escapeHtml } from '../js/core/dom.js'
import { bufferToBase64, formatBytes, lineValues, lines, statusLabel } from '../js/core/format.js'
import { request } from '../js/core/http.js'
import { replaceState, state } from '../js/core/state.js'

const firstNode = { id: 'first' }
const root = {
  querySelector: selector => selector === '.first' ? firstNode : null,
  querySelectorAll: () => [firstNode],
}
assert.equal($('.first', root), firstNode)
assert.deepEqual($$('.item', root), [firstNode])
assert.equal(escapeHtml('<b>'), '&lt;b&gt;')

assert.equal(lines(['a', 'b']), 'a\nb')
assert.deepEqual(lineValues(' a\n\nb '), ['a', 'b'])
assert.equal(statusLabel('effective'), '有效')
assert.equal(formatBytes(1024), '1.0 KiB')
assert.equal(bufferToBase64(Uint8Array.from([65, 66]).buffer), 'QUI=')

replaceState({ processes: [{ id: 'p1' }] })
assert.equal(state.processes[0].id, 'p1')

const requests = []
globalThis.fetch = async (path, options) => {
  requests.push({ path, options })
  return { ok: true, json: async () => ({ saved: true }) }
}
assert.deepEqual(await request('/api/state'), { saved: true })
assert.deepEqual(requests[0], {
  path: '/api/state',
  options: { method: 'GET', headers: undefined, body: undefined },
})
await request('/api/settings', { method: 'PUT', body: { enabled: true } })
assert.deepEqual(requests[1], {
  path: '/api/settings',
  options: {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ enabled: true }),
  },
})

globalThis.fetch = async () => ({
  ok: false,
  json: async () => ({ detail: [{ msg: '字段必填' }, { msg: '格式错误' }] }),
})
await assert.rejects(request('/api/settings'), { message: '字段必填；格式错误' })

console.log('core-modules-check: ok')
