import { $, $$ } from '../core/dom.js'
import { toast } from './feedback.js'
import { bindFormLabels, clearFieldError, validateDialogForm } from './form.js'
import { applyPermissions } from '../core/session.js'

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

$$('.dialog-close', dialog).forEach(button => button.onclick = () => void dialog.requestClose?.())
dialog.addEventListener('cancel', event => { event.preventDefault(); void dialog.requestClose?.() })
confirmDialog.addEventListener('cancel', event => { event.preventDefault(); void closeAnimatedDialog(confirmDialog, 'cancel') })
$$('button[value]', confirmDialog).forEach(button => button.onclick = event => {
  event.preventDefault()
  void closeAnimatedDialog(confirmDialog, button.value)
})

export function confirmAction(message, detail = '', options = {}) {
  const trigger = document.activeElement
  confirmMessage.textContent = message
  confirmDetail.textContent = detail
  confirmDetail.hidden = !detail
  confirmDialog.returnValue = 'cancel'
  $('#confirm-title').textContent = options.title || '确认操作'
  $('button[value="confirm"]', confirmDialog).textContent = options.confirmLabel || '确认删除'
  $('button[value="confirm"]', confirmDialog).className = 'button '+(options.tone==='primary'?'primary':'danger solid')
  return new Promise(resolve => {
    confirmDialog.addEventListener('close', () => {
      if (trigger instanceof HTMLElement) trigger.focus()
      resolve(confirmDialog.returnValue === 'confirm')
    }, { once: true })
    showAnimatedDialog(confirmDialog)
    $('button[value="cancel"]', confirmDialog).focus()
  })
}

export function openDialog(title, subtitle, html, onSave, options = {}) {
  const trigger = document.activeElement
  let dirty=false, closing=false, busy=false
  // The shared shell may retain disabled controls from the previous upload.
  $$('.dialog-close', dialog).forEach(button => { button.disabled = false })
  dialog.requestClose=async()=>{
    if(busy||closing)return
    closing=true
    try{
      if(options.guardChanges&&dirty&&!await confirmAction('放弃未保存的修改？','关闭后本次未保存的内容会丢失，已经保存的草稿仍然保留。',{confirmLabel:'放弃修改'}))return
      await closeAnimatedDialog(dialog)
    }finally{closing=false}
  }
  $('#dialog-title').textContent = title
  $('#dialog-subtitle').textContent = subtitle
  dialogContent.innerHTML = html
  bindFormLabels(dialogContent)
  dialogContent.oninput = event => {
    dirty=true
    if (event.target.matches('input, textarea, select')) clearFieldError(event.target)
  }
  dialogContent.onchange = () => { dirty=true }
  dialog.classList.toggle('wide', options.wide === true)
  dialog.classList.toggle('skill-dialog', options.kind === 'skill')
  dialogSave.hidden = options.readOnly === true
  dialogSave.disabled = false
  dialogSave.textContent = options.saveLabel || '保存'
  dialogSave.onclick = async (event) => {
    event.preventDefault()
    if (!validateDialogForm(dialog)) return
    dialogSave.disabled = true
    busy=true
    try {
      const saved = await onSave()
      if (saved === false) return
      await closeAnimatedDialog(dialog)
      await options.afterSave?.()
      toast(options.successMessage || '已保存')
    } catch (error) {
      let inline = dialogContent.querySelector('.dialog-request-error')
      if (!inline) { inline = document.createElement('p'); inline.className = 'dialog-request-error identity-error'; inline.setAttribute('role','alert'); dialogContent.append(inline) }
      inline.textContent = error.message
      toast(error.message, true)
    } finally {
      busy=false
      dialogSave.disabled = false
    }
  }
  dialog.addEventListener('close', () => {
    if (!dialog.open && !confirmDialog.open && trigger instanceof HTMLElement) trigger.focus()
  }, { once: true })
  showAnimatedDialog(dialog)
  applyPermissions(dialogContent)
  return {
    close: returnValue => closeAnimatedDialog(dialog, returnValue),
    element: dialog,
    saveButton: dialogSave,
    setBusy:value=>{busy=value;$$('.dialog-close',dialog).forEach(button=>button.disabled=value)},
  }
}
