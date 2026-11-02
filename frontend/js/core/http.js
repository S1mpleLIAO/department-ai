import { identity, spaceId } from './session.js'

export async function request(path, { method = 'GET', body } = {}) {
  const headers = { 'X-Department-Space': spaceId }
  if (identity?.csrfToken) headers['X-CSRF-Token'] = identity.csrfToken
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = await response.json()
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map(item => item.msg).join('；')
      : payload.detail
    const error = new Error(detail || payload.error || '请求失败')
    error.status = response.status
    if (response.status === 401 && identity && path !== '/api/auth/login') window.dispatchEvent(new Event('identity-expired'))
    throw error
  }
  return payload
}
