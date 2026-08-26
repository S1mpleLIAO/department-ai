export function lines(value = []) { return value.join('\n') }
export function lineValues(value = '') { return value.split('\n').map(item => item.trim()).filter(Boolean) }
export function formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '—' }
export function statusLabel(value) { return ({ draft: '草稿', effective: '有效', obsolete: '已废止' })[value] || value }
export function formatBytes(size = 0) { return size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KiB` : `${(size / 1024 / 1024).toFixed(1)} MiB` }

export function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768))
  return btoa(binary)
}
