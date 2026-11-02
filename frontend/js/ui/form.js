import { $, $$ } from '../core/dom.js'

let generatedControlId = 0

export function bindFormLabels(root) {
  $$('.field', root).forEach(field => {
    const label = $('label', field)
    const control = $('input:not([type="hidden"]), textarea, select', field)
    if (!label || !control) return
    if (!control.id) control.id = `field-control-${++generatedControlId}`
    label.htmlFor = control.id
  })
}

export function clearFieldError(control) {
  control.removeAttribute('aria-invalid')
  const error = control.closest('.field')?.querySelector('.field-error')
  if (error) {
    control.removeAttribute('aria-describedby')
    error.remove()
  }
}

export function validateDialogForm(root) {
  const controls = $$('input, textarea, select', root).filter(control => !control.disabled && control.type !== 'hidden')
  controls.forEach(clearFieldError)
  const invalid = controls.find(control => !control.checkValidity())
  if (!invalid) return true
  invalid.setAttribute('aria-invalid', 'true')
  const field = invalid.closest('.field')
  if (field) {
    const label = $('label', field)?.textContent.trim() || '此字段'
    const error = document.createElement('small')
    error.className = 'field-error'
    error.id = (invalid.id || 'field') + '-error'
    invalid.setAttribute('aria-describedby',error.id)
    error.textContent = invalid.validity.valueMissing ? `请填写${label}` : `请检查${label}的格式`
    field.append(error)
  }
  invalid.focus()
  return false
}
