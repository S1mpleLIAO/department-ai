import { $, $$, escapeHtml } from '../core/dom.js'
import { request } from '../core/http.js'
import { replaceState, state } from '../core/state.js'
import { dialogContent, openDialog } from '../ui/dialog.js'
import { serviceBadge, setAction } from '../ui/feedback.js'
import { chunkSettingsForm, chunkSettingsSummary, collectChunkSettings, openPurposeManager, toggleChunkFields } from './knowledge/purposes.js'

const content = $('#content')

async function refreshSettings(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

function principleRow(value = '', index = 0) {
  return `<div class="principle-row"><span class="principle-number">${index + 1}</span><textarea class="principle-text" rows="2" required>${escapeHtml(value)}</textarea><div class="actions"><button type="button" class="button small principle-up" aria-label="上移">↑</button><button type="button" class="button small principle-down" aria-label="下移">↓</button><button type="button" class="button small danger principle-remove">删除</button></div></div>`
}

function renumberPrinciples() {
  $$('.principle-row').forEach((row, index) => $('.principle-number', row).textContent = index + 1)
}

function settingsPayload(overrides = {}) {
  return {
    assistant: state.settings.assistant,
    chunking: state.settings.chunking,
    retrieval: state.settings.retrieval,
    embeddingModel: state.settings.embeddingModel,
    rerankModel: state.settings.rerankModel,
    ...overrides,
  }
}

function bindPrincipleEditor() {
  $('#add-principle').onclick = () => { $('#principles-editor').insertAdjacentHTML('beforeend', principleRow('', $$('.principle-row').length)); renumberPrinciples() }
  $('#principles-editor').onclick = event => {
    const row = event.target.closest('.principle-row')
    if (!row) return
    if (event.target.closest('.principle-remove')) row.remove()
    if (event.target.closest('.principle-up') && row.previousElementSibling) row.parentElement.insertBefore(row, row.previousElementSibling)
    if (event.target.closest('.principle-down') && row.nextElementSibling) row.parentElement.insertBefore(row.nextElementSibling, row)
    renumberPrinciples()
  }
}

function openAssistantSettings(afterSave) {
  const assistant = state.settings.assistant
  openDialog('部门助手规则', '配置角色、工作原则和默认交互方式；新任务会通过 MCP 读取最新规则。', `
    <div class="settings-dialog-form">
      <div class="field"><label>角色定位</label><textarea id="assistant-role" required>${escapeHtml(assistant.role)}</textarea></div>
      <div class="field"><div class="field-heading"><label>工作原则</label><button type="button" id="add-principle" class="button small">+ 添加原则</button></div><div id="principles-editor" class="principles-editor">${assistant.principles.map(principleRow).join('')}</div></div>
      <div class="form-grid compact-form-grid">
        <div class="field"><label>默认语言</label><select id="assistant-language"><option value="zh-CN" ${assistant.defaultLanguage === 'zh-CN' ? 'selected' : ''}>中文</option><option value="en" ${assistant.defaultLanguage === 'en' ? 'selected' : ''}>英文</option></select></div>
        <div class="assistant-defaults"><label class="check-field"><input id="assistant-draft" type="checkbox" ${assistant.draftByDefault ? 'checked' : ''}> 生成内容默认视为草稿</label><label class="check-field"><input id="assistant-ask" type="checkbox" ${assistant.askWhenMissing ? 'checked' : ''}> 关键信息缺失时先询问</label></div>
      </div>
    </div>`, async () => {
      await request('/api/settings', { method: 'PUT', body: settingsPayload({ assistant: {
        role: $('#assistant-role').value.trim(),
        principles: $$('.principle-text', dialogContent).map(node => node.value.trim()).filter(Boolean),
        defaultLanguage: $('#assistant-language').value,
        draftByDefault: $('#assistant-draft').checked,
        askWhenMissing: $('#assistant-ask').checked,
      } }) })
    }, { wide: true, successMessage: '部门助手规则已保存', afterSave })
  bindPrincipleEditor()
}

function openChunkingSettings(afterSave) {
  openDialog('默认分块设置', '作为文档用途和单个文档未覆盖规则时的系统默认值。', `
    <div class="settings-dialog-form"><div class="settings-dialog-note">上传文档时仍可以按用途或单个文件覆盖此设置。</div>${chunkSettingsForm(state.settings.chunking)}</div>`, async () => {
      await request('/api/settings', { method: 'PUT', body: settingsPayload({ chunking: collectChunkSettings() }) })
    }, { wide: true, successMessage: '默认分块设置已保存', afterSave })
  toggleChunkFields()
  $('#chunk-mode').onchange = toggleChunkFields
}

function openRetrievalSettings(afterSave) {
  const retrieval = state.settings.retrieval
  openDialog('检索与推荐', '配置向量初召回、重排序和最终推荐数量。', `
    <div class="form-grid settings-dialog-form compact-form-grid">
      <div class="field"><label>向量召回数量</label><input id="vector-recall" type="number" min="1" max="100" value="${retrieval.vectorRecall}"></div>
      <div class="field"><label>Rerank 保留数量</label><input id="rerank-top" type="number" min="1" max="50" value="${retrieval.rerankTopN}"></div>
      <div class="field"><label>模板推荐数量</label><input id="recommend-count" type="number" min="1" max="10" value="${retrieval.recommendCount}"></div>
      <div class="field"><label>Score 阈值</label><input id="score-threshold" type="number" min="0" max="1" step="0.05" value="${retrieval.scoreThreshold ?? 0.5}"></div>
      <label class="check-field full"><input id="threshold-enabled" type="checkbox" ${retrieval.scoreThreshold === null ? '' : 'checked'}> 启用 Score 阈值</label>
      <p class="muted small-copy full">知识量较少时建议关闭阈值，先由 Rerank 和推荐数量筛选结果。</p>
    </div>`, async () => {
      await request('/api/settings', { method: 'PUT', body: settingsPayload({ retrieval: {
        vectorRecall: Number($('#vector-recall').value),
        rerankTopN: Number($('#rerank-top').value),
        recommendCount: Number($('#recommend-count').value),
        scoreThreshold: $('#threshold-enabled').checked ? Number($('#score-threshold').value) : null,
      } }) })
    }, { successMessage: '检索与推荐设置已保存', afterSave })
}

function openModelSettings() {
  const settings = state.settings
  openDialog('模型与服务', '查看当前模型配置和基础服务连接状态。', `
    <div class="settings-dialog-form"><div class="form-grid compact-form-grid">
      <div class="field full"><label>Embedding 模型</label><input value="${escapeHtml(settings.embeddingModel)}" readonly></div>
      <div class="field full"><label>Rerank 模型</label><input value="${escapeHtml(settings.rerankModel)}" readonly></div>
    </div><div class="service-list">${serviceBadge(state.services.database, 'PostgreSQL / pgvector')}${serviceBadge(state.services.docling, 'Docling Serve')}${serviceBadge(state.services.siliconflow, 'Embedding / Rerank 已配置')}${serviceBadge(state.services.metadata, 'AI 元数据分析已配置')}${serviceBadge(state.services.harness, 'DeepSeek Harness')}</div><p class="muted small-copy">模型名称暂时只读，避免更换模型后旧向量失效。增加批量重建索引能力后再开放切换。</p></div>`, async () => {}, { readOnly: true })
}

function settingRow({ icon, title, description, summary, action, actionLabel, tone = '' }) {
  return `<article class="settings-row ${tone}">
    <span class="settings-row-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span>
    <div class="settings-row-body"><h3>${title}</h3><p>${description}</p><span class="settings-row-summary">${summary}</span></div>
    <button type="button" class="button settings-row-action" data-settings-action="${action}">${actionLabel}</button>
  </article>`
}

export function renderSettings(renderPage) {
  const settings = state.settings
  const afterSave = () => refreshSettings(renderPage)
  setAction('', null)
  const onlineServices = ['database', 'docling', 'siliconflow', 'metadata', 'harness'].filter(key => state.services[key]).length
  const icons = {
    chunking: '<path d="M4 6h16M4 12h10M4 18h16"/><path d="m17 10 3 2-3 2"/>',
    retrieval: '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5M7 10h6M10 7v6"/>',
    purposes: '<path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5M8 12h8M8 16h6"/>',
    assistant: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18.5 16.5 20 20l3.5 1.5L20 23l-1.5 3.5L17 23l-3.5-1.5L17 20z" transform="translate(-2 -2) scale(.9)"/>',
    models: '<path d="M8 3h8v4H8zM5 9h14v10H5z"/><path d="M9 13h.01M15 13h.01M9 16h6M3 12h2M19 12h2"/>',
  }
  content.innerHTML = `<div class="settings-workspace">
    <section class="settings-section settings-section-main">
      <header><div><h2>知识与检索</h2><p>管理文档如何入库、召回和推荐</p></div><span class="settings-section-count">3 项</span></header>
      <div class="settings-list">
        ${settingRow({ icon: icons.chunking, title: '默认分块设置', description: '用途未单独指定时采用的正文切块规则', summary: escapeHtml(chunkSettingsSummary(settings.chunking)), action: 'chunking', actionLabel: '配置分块' })}
        ${settingRow({ icon: icons.retrieval, title: '检索与推荐', description: '向量召回、Rerank 和模板推荐数量', summary: `召回 ${settings.retrieval.vectorRecall} · Rerank ${settings.retrieval.rerankTopN} · 推荐 ${settings.retrieval.recommendCount}`, action: 'retrieval', actionLabel: '配置检索' })}
        ${settingRow({ icon: icons.purposes, title: '文档用途', description: '定义文档能否作为模板及是否建立正文索引', summary: `${state.purposes.length} 种用途 · ${state.documents.length} 份文档`, action: 'purposes', actionLabel: '管理用途' })}
      </div>
    </section>
    <div class="settings-secondary">
      <section class="settings-section">
        <header><div><h2>助手行为</h2><p>控制部门助手的默认工作方式</p></div></header>
        <div class="settings-list">${settingRow({ icon: icons.assistant, title: '部门助手规则', description: '角色定位、工作原则和默认交互方式', summary: `${settings.assistant.principles.length} 条原则 · ${settings.assistant.defaultLanguage === 'zh-CN' ? '中文' : '英文'}`, action: 'assistant', actionLabel: '配置规则' })}</div>
      </section>
      <section class="settings-section">
        <header><div><h2>模型与服务</h2><p>确认知识处理和对话服务状态</p></div><span class="service-health ${onlineServices === 5 ? 'ok' : 'off'}"><i></i>${onlineServices}/5 正常</span></header>
        <div class="settings-list">${settingRow({ icon: icons.models, title: '模型与服务', description: '查看嵌入、重排模型和基础服务连接', summary: onlineServices === 5 ? '全部基础服务可用' : `${5 - onlineServices} 项服务需要检查`, action: 'models', actionLabel: '查看状态', tone: onlineServices === 5 ? 'service-ok' : 'service-off' })}</div>
      </section>
    </div>
  </div>`
  const actions = {
    assistant: () => openAssistantSettings(afterSave),
    chunking: () => openChunkingSettings(afterSave),
    retrieval: () => openRetrievalSettings(afterSave),
    models: openModelSettings,
    purposes: () => openPurposeManager(renderPage),
  }
  $$('.settings-row-action').forEach(button => button.onclick = actions[button.dataset.settingsAction])
}
