import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
import { JSDOM } from '../../../../deepseek-harness/node_modules/jsdom/lib/api.js'

export async function createDom({ hash = 'dashboard', state, onRequest = () => {} }) {
  const root = new URL('../../', import.meta.url)
  const html = await readFile(new URL('index.html', root), 'utf8')
  const dom = new JSDOM(html, {
    url: `http://127.0.0.1:3081/department#${hash}`,
    pretendToBeVisual: true,
  })
  const { window } = dom
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true }
  window.HTMLDialogElement.prototype.close = function (returnValue = '') {
    this.returnValue = returnValue
    this.open = false
    this.dispatchEvent(new window.Event('close'))
  }
  window.requestAnimationFrame = callback => callback()
  window.fetch = globalThis.fetch = async (url, options = {}) => {
    onRequest(String(url), options)
    return { ok: true, json: async () => structuredClone(state) }
  }
  for (const name of ['window', 'document', 'location', 'history', 'navigator', 'HTMLElement', 'HTMLDialogElement', 'Event', 'HashChangeEvent', 'File', 'FileReader']) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value: window[name],
    })
  }
  const entry = pathToFileURL(new URL('app.js', root).pathname)
  await import(`${entry.href}?test=${Date.now()}`)
  await new Promise(resolve => setTimeout(resolve, 0))
  return dom
}
