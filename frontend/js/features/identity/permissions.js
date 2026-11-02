import { escapeHtml as e } from '../../core/dom.js'

// Keep selection dependencies identical to core/security.py validate_actions.
function prerequisite(module, action) {
  if(module === 'assistant' || action.endsWith('.use')) return null
  const read = module + (module === 'skills' ? '.source_read' : '.read')
  return action === read ? null : read
}

export function permissionTree(modules, selected = [], readonly = false) {
  const chosen = new Set(selected)
  return `<div class="permission-tree">${modules.map(m => {
    const count = m.items.filter(a => chosen.has(a.id)).length
    return `<details class="permission-module" open><summary>${e(m.name)}<span>${count} / ${m.items.length} 项</span></summary>
      ${readonly ? '' : `<label class="checkbox permission-module-toggle"><input type="checkbox" data-module="${e(m.module)}">选择${e(m.name)}全部操作</label>`}
      <div class="permission-children">${m.items.map(a => `<label class="checkbox"><input type="checkbox" value="${e(a.id)}" data-action-module="${e(m.module)}" ${chosen.has(a.id) ? 'checked' : ''} ${readonly ? 'disabled' : ''}>${e(a.name)}</label>`).join('')}</div></details>`
  }).join('')}</div>`
}

export function bindPermissionTree(root) {
  const all = selector => [...root.querySelectorAll(selector)]
  const children = module => all('[data-action-module]').filter(c => c.dataset.actionModule === module)
  function sync() {
    all('[data-module]').forEach(parent => {
      const items = children(parent.dataset.module), n = items.filter(c => c.checked).length
      parent.checked = n === items.length
      parent.indeterminate = n > 0 && n < items.length
      parent.closest('details').querySelector('summary span').textContent = `${n} / ${items.length} 项`
    })
  }
  all('[data-module]').forEach(parent => parent.onchange = () => {
    children(parent.dataset.module).forEach(c => c.checked = parent.checked)
    sync()
  })
  all('[data-action-module]').forEach(child => child.onchange = () => {
    const items = children(child.dataset.actionModule)
    if(child.checked) {
      const required = prerequisite(child.dataset.actionModule, child.value)
      const base = items.find(c => c.value === required)
      if(base) base.checked = true
    } else {
      items.filter(c => prerequisite(child.dataset.actionModule, c.value) === child.value).forEach(c => c.checked = false)
    }
    sync()
  })
  sync()
}
