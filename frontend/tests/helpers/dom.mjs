import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
import { registerHooks } from 'node:module'
const { JSDOM } = await import(process.env.DEPARTMENT_TEST_JSDOM || '../../../../deepseek-harness/node_modules/jsdom/lib/api.js')

export async function createDom({ hash = 'dashboard', state, onRequest = () => {}, asyncDialogClose = false }) {
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
    const dispatchClose = () => this.dispatchEvent(new window.Event('close'))
    if (asyncDialogClose) setTimeout(dispatchClose, 0)
    else dispatchClose()
  }
  window.requestAnimationFrame = callback => callback()
  window.fetch = globalThis.fetch = async (url, options = {}) => {
    onRequest(String(url), options)
    const identity={user:{id:'test-admin',companyId:'zkxk',superadmin:true,mustChangePassword:false,displayName:'测试管理员'},csrfToken:'test-csrf',spaces:[{id:'zkxk',name:'中科信控'}],permissions:{},capabilities:{assistant:false,review:false}}
    return { ok: true, json: async () => structuredClone(String(url)==='/api/me' ? identity : state) }
  }
  for (const name of ['window', 'document', 'location', 'history', 'navigator', 'sessionStorage', 'HTMLElement', 'HTMLDialogElement', 'Event', 'HashChangeEvent', 'File', 'FileReader']) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value: window[name],
    })
  }
  const entry = pathToFileURL(new URL('js/main.js', root).pathname)
  const moduleHooks = registerHooks({
    load(url, context, nextLoad) {
      const target = new URL(url)
      if (target.protocol === 'file:' && target.href.startsWith(root.href) && target.pathname.endsWith('.js')) {
        return nextLoad(url, { ...context, format: 'module' })
      }
      return nextLoad(url, context)
    },
  })
  try {
    await import(`${entry.href}?test=${Date.now()}`)
  } finally {
    moduleHooks.deregister()
  }
  await new Promise(resolve => setTimeout(resolve, 0))
  return dom
}
