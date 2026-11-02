export let identity = null
export let spaceId = ''
export function setIdentity(value) {
  identity = value
  const saved = sessionStorage.getItem('department-space')
  spaceId = value?.spaces.find(s => s.id === saved)?.id || value?.spaces.find(s => s.id === value.user.companyId)?.id || value?.spaces[0]?.id || ''
}
export function clearIdentity() { identity = null; spaceId = '' }
export function can(...actions) {
  if(spaceId==='legacy' && actions.some(a=>!a.endsWith('.read')&&!a.endsWith('.source_read')))return false
  return Boolean(identity && (identity.user.superadmin || actions.every(a => identity.permissions[spaceId]?.includes(a))))
}
export function fileUrl(path) { return path + (path.includes('?') ? '&' : '?') + 'space=' + encodeURIComponent(spaceId) }
export function requiresReview(module) { return Boolean(identity) && !can(module+'.publish_direct') }
export function pageAllowed(page) {
  if (!identity || identity.user.mustChangePassword) return false
  const permissions = { processes:'processes.read', knowledge:'knowledge.read', skills:'skills.source_read' }
  if (page === 'assistant') return Boolean(identity.capabilities?.assistant) && can('assistant.use')
  if (page === 'admin' || page === 'settings') return identity.user.superadmin
  return !permissions[page] || can(permissions[page])
}
export function applyPermissions(root = document) {
  const gates = {
    '.edit-process':'processes.edit_any', '.delete-process':'processes.archive',
    '.edit-skill':'skills.edit_any', '.delete-skill':'skills.archive',
    '#add-category, .category-edit, #add-purpose, .edit-purpose, .delete-purpose, #upload-category-create, #batch-category-create':'catalog.manage',
    '#edit-document':'knowledge.edit_any', '#reindex-document':'knowledge.reindex',
    '#delete-document':'knowledge.archive', 'a[href*="/source"]':'knowledge.source_download',
  }
  for (const [selector, actions] of Object.entries(gates)) {
    root.querySelectorAll(selector).forEach(node => { if (!can(...actions.split(' '))) {node.hidden = true} })
  }
  root.querySelectorAll('a[href^="/api/"]').forEach(a => {
    const path = new URL(a.href, location.origin)
    path.searchParams.set('space', spaceId)
    a.href = path.pathname + path.search
  })
}

