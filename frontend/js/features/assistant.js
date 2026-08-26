import { $, escapeHtml } from '../core/dom.js'
import { state } from '../core/state.js'
import { setAction } from '../ui/feedback.js'

const assistantHost = $('#assistant-host')

export function renderAssistant() {
  setAction('', null)
  if (!assistantHost.firstElementChild) assistantHost.innerHTML = `<div class="assistant-page"><iframe class="assistant-frame" src="${escapeHtml(state.services.harnessUrl)}" title="DeepSeek Harness AI 助手"></iframe></div>`
}
