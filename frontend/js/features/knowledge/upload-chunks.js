import { $, $$, escapeHtml } from '../../core/dom.js'
import { chunkSettingsForm, collectChunkSettings, setChunkSettings, toggleChunkFields } from './purposes.js'

export { collectChunkSettings, setChunkSettings, toggleChunkFields }

export function chunkPanelHtml(settings) {
  return `<div id="chunk-fields"><h3>分块设置</h3>${chunkSettingsForm(settings)}</div>`
}

export function renderChunkPreview(chunks) {
  const target = $('#chunk-preview')
  const parentMode = $('#chunk-mode')?.value === 'parent-child'
  target.innerHTML = chunks.map(chunk => `<article class="chunk-card ${chunk.enabled ? '' : 'disabled'}" data-index="${chunk.index}" data-parent="${chunk.parentIndex ?? ''}">
    <header><label><input class="chunk-enabled" type="checkbox" ${chunk.enabled ? 'checked' : ''} ${parentMode && chunk.parentIndex === null ? 'disabled' : ''}> ${parentMode && chunk.parentIndex === null ? '父块上下文' : parentMode ? '子块检索' : '使用'}</label><span>${escapeHtml(chunk.sectionPath || '正文')} · 约 ${chunk.tokenCount} tokens${chunk.parentIndex === null ? '' : ` · 父块 #${chunk.parentIndex + 1}`}</span></header>
    <textarea class="chunk-content">${escapeHtml(chunk.content)}</textarea>
  </article>`).join('')
  $$('.chunk-enabled', target).forEach(input => input.onchange = () => input.closest('.chunk-card').classList.toggle('disabled', !input.checked))
}

export function collectPreviewChunks() {
  return $$('.chunk-card', $('#chunk-preview')).map(card => ({
    parentIndex: card.dataset.parent === '' ? null : Number(card.dataset.parent),
    sectionPath: $('header span', card).textContent.split(' · ')[0],
    content: $('.chunk-content', card).value,
    enabled: $('.chunk-enabled', card).checked,
  }))
}

export function hasEnabledChunk() {
  return $$('.chunk-enabled', $('#chunk-preview')).some(input => input.checked)
}

export function validatePreviewChunks(errorNode) {
  const contents = $$('.chunk-content', $('#chunk-preview'))
  contents.forEach(control => {
    control.removeAttribute('aria-invalid')
    control.removeAttribute('aria-describedby')
  })
  const invalid = contents.find(control => !control.value.trim())
  if (!invalid) return true
  errorNode.textContent = '分块正文不能为空，请填写正文或重新生成索引预览。'
  errorNode.hidden = false
  invalid.setAttribute('aria-invalid', 'true')
  invalid.setAttribute('aria-describedby', errorNode.id)
  invalid.focus()
  return false
}

export function renderIndexPlan(purpose) {
  const base = '<b>将建立的索引</b><span>文档目录索引（标题、摘要、关键词和正文摘要）</span>'
  const detail = purpose?.canGenerateTemplate && purpose?.chunkBody
    ? '<span>整份模板推荐索引</span><span>正文分块索引</span>'
    : purpose?.canGenerateTemplate
      ? '<span>整份模板推荐索引</span><span>正文不切块，完整正文仍会保存</span>'
      : purpose?.chunkBody
        ? '<span>正文分块索引</span>'
        : '<span>正文不切块，完整正文仍会保存</span>'
  const html = `${base}${detail}`
  const target = $('#index-plan')
  if (target) target.innerHTML = html
  return html
}
