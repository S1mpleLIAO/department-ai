import { $, $$, escapeHtml } from '../../core/dom.js'
import { formatDate } from '../../core/format.js'
import { request } from '../../core/http.js'
import { replaceState, state } from '../../core/state.js'
import { confirmAction, openDialog } from '../../ui/dialog.js'
import { setAction, toast } from '../../ui/feedback.js'
import { openSkillEditor } from './editor.js'
import { identity } from '../../core/session.js'
import { beginEdit } from '../reviews/edit-entry.js'

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
        <div class="actions"><button class="button small view-skill" data-id="${skill.id}">查看</button><button class="button small edit-skill" data-id="${skill.id}">编辑</button><button class="button small danger delete-skill" data-id="${skill.id}" ${!skill.enabled ? 'disabled' : ''}>停用</button></div></div>
      <div class="meta"><span>${skillResourceSummary(skill)}</span><span>更新于 ${formatDate(skill.updatedAt)}</span></div>
    </article>`).join('')}</div>` : `<div class="empty"><b>还没有特殊技能</b><p>常规任务仍按业务流程和知识库处理；只有需要固定专业方法时才创建技能。</p></div>`
  $$('.edit-skill').forEach(button => {
    if(identity)button.textContent='修改送审'
    button.onclick = () => identity ? beginEdit('skills',button.dataset.id,button) : openSkillEditor(state.skills.find(item => item.id === button.dataset.id), () => refreshSkills(renderPage))
  })
  $$('.view-skill').forEach(button => button.onclick = () => {
    const skill=state.skills.find(item => item.id === button.dataset.id)
    const resources=(skill.resources||[]).map(r=>`<li><a download href="/api/skills/${encodeURIComponent(skill.id)}/resources/${r.path.split('/').map(encodeURIComponent).join('/')}">${escapeHtml(r.path)}</a></li>`).join('')
    openDialog(skill.name,skill.description,`<pre class="identity-source">${escapeHtml(skill.instructions || skill.content || '')}</pre>${resources?'<h3>附件</h3><ul>'+resources+'</ul>':''}${skill.reviewPublished?'<p>此技能来自已审核版本；修改需提交审核，发布前继续使用当前版本。</p>':''}`,async()=>{}, {wide:true,readOnly:true})
  })
  $$('.delete-skill').forEach(button => button.onclick = async () => {
    if (!await confirmAction('停用这个技能？', '技能内容和附加资源将保留，停用后不再用于执行任务。',{confirmLabel:'停用技能'})) return
    try {
      await request(`/api/skills/${encodeURIComponent(button.dataset.id)}`, { method: 'DELETE' })
      await refreshSkills(renderPage)
      toast('技能已停用')
    } catch (error) { toast(error.message, true) }
  })
}
