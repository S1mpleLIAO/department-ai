import { $, $$, escapeHtml } from '../../core/dom.js'
import { formatDate } from '../../core/format.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction } from '../../ui/dialog.js'
import { setAction, toast } from '../../ui/feedback.js'
import { openSkillEditor } from './editor.js'

const content = $('#content')

async function refreshSkills(renderPage) {
  replaceState(await request('/api/state'))
  renderPage()
}

function skillResourceSummary(skill) {
  const labels = { scripts: '脚本', references: '参考资料', assets: '素材' }
  const parts = Object.entries(labels).filter(([kind]) => skill.resourceCounts?.[kind]).map(([kind, label]) => `${skill.resourceCounts[kind]} 个${label}`)
  return parts.length ? parts.join(' · ') : '暂无附加资源'
}

export function renderSkills(renderPage) {
  setAction('+ 新建技能', () => openSkillEditor(undefined, () => refreshSkills(renderPage)))
  content.innerHTML = state.skills.length ? `<div class="process-list skills-grid">${state.skills.map(skill => `
    <article class="item-card skill-card">
      <div class="item-head"><div><div class="title-line"><h3>${escapeHtml(skill.name)}</h3><span class="tag ${skill.valid === false ? 'obsolete' : skill.enabled ? 'high' : 'obsolete'}">${skill.valid === false ? '待修复' : skill.enabled ? '已启用' : '已停用'}</span></div><p>${escapeHtml(skill.error || skill.description)}</p></div>
        <div class="actions"><button class="button small edit-skill" data-id="${skill.id}">编辑</button><button class="button small danger delete-skill" data-id="${skill.id}">删除</button></div></div>
      <div class="meta"><span>${skillResourceSummary(skill)}</span><span>更新于 ${formatDate(skill.updatedAt)}</span></div>
    </article>`).join('')}</div>` : `<div class="empty"><b>还没有特殊技能</b><p>常规任务仍按业务流程和知识库处理；只有需要固定专业方法时才创建技能。</p></div>`
  $$('.edit-skill').forEach(button => button.onclick = () => openSkillEditor(state.skills.find(item => item.id === button.dataset.id), () => refreshSkills(renderPage)))
  $$('.delete-skill').forEach(button => button.onclick = async () => {
    if (!await confirmAction('确定删除这个技能吗？', '对应的 SKILL.md 文件会一并删除。')) return
    try {
      await request(`/api/skills/${encodeURIComponent(button.dataset.id)}`, { method: 'DELETE' })
      await refreshSkills(renderPage)
      toast('技能已删除')
    } catch (error) { toast(error.message, true) }
  })
}
