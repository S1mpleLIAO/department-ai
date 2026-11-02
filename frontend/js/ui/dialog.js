import { $, $$ } from '../core/dom.js'
import { toast } from './feedback.js'
import { bindFormLabels, clearFieldError, validateDialogForm } from './form.js'

const dialog = $('#editor-dialog')
export const dialogContent = $('#dialog-content')
const dialogSave = $('#dialog-save')
const confirmDialog = $('#confirm-dialog')
const confirmMessage = $('#confirm-message')
const confirmDetail = $('#confirm-detail')
const dialogCloseDelay = 180

function showAnimatedDialog(node) {
  node.classList.remove('is-open', 'is-closing')
  node.showModal()
  const nextFrame = window.requestAnimationFrame || (callback => setTimeout(callback, 0))
  nextFrame(() => node.classList.add('is-open'))
}

function closeAnimatedDialog(node, returnValue = '') {
  if (!node.open) return Promise.resolve()
  if (node.closePromise) return node.closePromise
  node.classList.remove('is-open')
  node.classList.add('is-closing')
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  node.closePromise = new Promise(resolve => {
    node.addEventListener('close', () => {
      node.classList.remove('is-closing')
      node.closePromise = null
      resolve()
    }, { once: true })
    setTimeout(() => {
      node.close(returnValue)
    }, reducedMotion ? 0 : dialogCloseDelay)
  })
  return node.closePromise
}

$$('.dialog-close', dialog).forEach(button => button.onclick = () => void closeAnimatedDialog(dialog))
dialog.addEventListener('cancel', event => { event.preventDefault(); void closeAnimatedDialog(dialog) })
confirmDialog.addEventListener('cancel', event => { event.preventDefault(); void closeAnimatedDialog(confirmDialog, 'cancel') })
$$('button[value]', confirmDialog).forEach(button => button.onclick = event => {
  event.preventDefault()
  void closeAnimatedDialog(confirmDialog, button.value)
})

export function confirmAction(message, detail = '') {
  const trigger = document.activeElement
  confirmMessage.textContent = message
  confirmDetail.textContent = detail
  confirmDetail.hidden = !detail
  confirmDialog.returnValue = 'cancel'
  return new Promise(resolve => {
    confirmDialog.addEventListener('close', () => {
      if (trigger instanceof HTMLElement) trigger.focus()
      resolve(confirmDialog.returnValue === 'confirm')
    }, { once: true })
    showAnimatedDialog(confirmDialog)
  })
}

export function openDialog(title, subtitle, html, onSave, options = {}) {
  const trigger = document.activeElement
  $('#dialog-title').textContent = title
  $('#dialog-subtitle').textContent = subtitle
  dialogContent.innerHTML = html
  bindFormLabels(dialogContent)
  dialogContent.oninput = event => {
    if (event.target.matches('input, textarea, select')) clearFieldError(event.target)
  }
  dialog.classList.toggle('wide', options.wide === true)
  dialog.classList.toggle('skill-dialog', options.kind === 'skill')
  dialogSave.hidden = options.readOnly === true
  dialogSave.disabled = false
  dialogSave.textContent = options.saveLabel || '保存'
  dialogSave.onclick = async (event) => {
    event.preventDefault()
    if (!validateDialogForm(dialog)) return
    dialogSave.disabled = true
    try {
      await onSave()
      await closeAnimatedDialog(dialog)
      await options.afterSave?.()
      toast(options.successMessage || '已保存')
    } catch (error) {
      toast(error.message, true)
    } finally {
      dialogSave.disabled = false
    }
  }
  dialog.addEventListener('close', () => {
    if (!dialog.open && !confirmDialog.open && trigger instanceof HTMLElement) trigger.focus()
  }, { once: true })
  showAnimatedDialog(dialog)
  return {
    close: returnValue => closeAnimatedDialog(dialog, returnValue),
    element: dialog,
    saveButton: dialogSave,
  }
}
