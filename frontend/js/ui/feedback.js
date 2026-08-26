import { $ } from '../core/dom.js'

const toastNode = $('#toast')
const pageAction = $('#page-action')
const pageSecondaryAction = $('#page-secondary-action')

export function toast(message, error = false) {
  toastNode.textContent = message
  toastNode.className = `toast show${error ? ' error' : ''}`
  if (toastNode.showPopover && !toastNode.matches(':popover-open')) toastNode.showPopover()
  clearTimeout(toast.timer)
  toast.timer = setTimeout(() => {
    toastNode.className = 'toast'
    if (toastNode.hidePopover && toastNode.matches(':popover-open')) toastNode.hidePopover()
  }, 3000)
}

export function serviceBadge(ok, label) {
  return `<span class="service-badge ${ok ? 'ok' : 'off'}"><i></i>${label}</span>`
}

export function setAction(label, handler) {
  pageAction.hidden = !label
  pageAction.textContent = label || ''
  pageAction.onclick = handler || null
}

export function setSecondaryAction(label, handler) {
  pageSecondaryAction.hidden = !label
  pageSecondaryAction.textContent = label || ''
  pageSecondaryAction.onclick = handler || null
}
