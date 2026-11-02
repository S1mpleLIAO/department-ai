import { $, $$, escapeHtml } from '../../core/dom.js'
import { bufferToBase64, formatBytes } from '../../core/format.js'
import { request } from '../../core/http.js'
import { applyPermissions, requiresReview } from '../../core/session.js'
import { dialogContent, openDialog } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'

function resourceUrl(skillId, path) {
  return `/api/skills/${encodeURIComponent(skillId)}/resources/${path.split('/').map(encodeURIComponent).join('/')}`
}

export function openSkillEditor(skill, afterSave, {draft=null}={}) {
  const review = Boolean(draft) || (!skill && requiresReview('skills'))
  const draftId = draft?.id || crypto.randomUUID()
  const current = skill || { name: '', description: '', instructions: '', enabled: true, resources: [] }
  const pendingResources = new Map()
  const removedResources = new Set()
  const resourceKinds = {
    scripts: { title: '脚本', description: 'Python、Shell 等辅助程序文件，当前只保存不自动执行', action: '添加脚本' },
    references: { title: '参考资料', description: '规则、说明、接口文档和专业资料', action: '添加资料' },
    assets: { title: '模板与素材', description: 'Word、Excel、图片等输出时使用的文件', action: '添加素材' },
  }
  openDialog(skill ? '编辑技能' : '新建技能', draft?.targetId?'正文与附件一起提交审核；发布前继续使用当前正式版本。':'只写特殊任务的专业方法；流程要求和知识内容仍分别维护在业务流程与知识库中。', `
    <div class="skill-form">
      <section class="skill-section">
        <div class="skill-section-heading"><span>1</span><div><b>基本信息</b><small>用于识别技能并判断何时调用</small></div></div>
        <div class="form-grid skill-basics-grid">
          <div class="field"><label>技能名称（英文）</label><input id="skill-name" value="${escapeHtml(current.name)}" placeholder="例如：contract-risk-review" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxlength="64" required><small>英文小写、数字和短横线，同时作为目录名和 frontmatter name。</small></div>
          <div class="field"><label>简短说明</label><input id="skill-description" value="${escapeHtml(current.description)}" placeholder="说明技能做什么、何时使用以及主要输出" maxlength="500" required><small>Harness 会根据这段说明判断是否调用该技能。</small></div>
        </div>
      </section>
      <section class="skill-section">
        <div class="skill-section-heading"><span>2</span><div><b>执行规则</b><small>保存为 SKILL.md 正文，支持 Markdown</small></div><code>SKILL.md</code></div>
        <textarea id="skill-instructions" class="skill-instructions" aria-label="执行规则" placeholder="## 操作步骤&#10;1. 确认用户需求&#10;2. 执行专业检查&#10;3. 按要求输出结果" required>${escapeHtml(current.instructions)}</textarea>
      </section>
      <section class="skill-section">
        <div class="skill-section-heading"><span>3</span><div><b>相关资源</b><small>AI 创建和人工上传的文件统一保存在技能目录中</small></div><code>可选</code></div>
        <div class="skill-resource-grid">${Object.entries(resourceKinds).map(([kind, definition]) => `
          <article class="skill-resource-card" data-resource-kind="${kind}">
            <header><div><b>${definition.title}</b><small>${definition.description}</small></div><label class="button small resource-picker" for="skill-resource-${kind}">${definition.action}<input id="skill-resource-${kind}" type="file" multiple data-resource-input="${kind}"></label></header>
            <div class="skill-resource-list" data-resource-list="${kind}"></div>
          </article>`).join('')}</div>
        <p class="skill-resource-note">在 SKILL.md 中使用相对路径引用资源，例如 <code>scripts/review.py</code> 或 <code>assets/template.docx</code>。页面选择的文件会在保存技能时上传。</p>
      </section>
      <label class="skill-toggle"><div><b>允许部门助手使用</b><span>关闭后保留 Skill 文件，但不会出现在模型和用户的可调用列表中。</span></div><input id="skill-enabled" type="checkbox" ${current.enabled ? 'checked' : ''}><i aria-hidden="true"></i></label>
    </div>`, async () => {
      const method = skill ? 'PUT' : 'POST'
      const path = skill ? `/api/skills/${encodeURIComponent(skill.id)}` : '/api/skills'
      const body = {
        name: $('#skill-name').value.trim(),
        description: $('#skill-description').value.trim(),
        instructions: $('#skill-instructions').value.trim(),
        enabled: $('#skill-enabled').checked,
      }
      if(review) {
        const resources=(draft?.data.resources||[]).filter(r=>!removedResources.has(r.path)&&!pendingResources.has(r.path))
        for(const [path,file] of pendingResources)resources.push({path,contentBase64:bufferToBase64(await file.arrayBuffer())})
        const data={skill:body,resources}
        await request(draft?'/api/reviews/'+draft.id:'/api/reviews',{method:draft?'PUT':'POST',body:draft?{revision:draft.revision,data}:{id:draftId,kind:'skills',data}})
        return
      }
      const result = await request(path, { method, body })
      const skillId = result.skill.id
      for (const path of removedResources) await request(resourceUrl(skillId, path), { method: 'DELETE' })
      for (const [path, file] of pendingResources) {
        await request(resourceUrl(skillId, path), { method: 'PUT', body: { contentBase64: bufferToBase64(await file.arrayBuffer()) } })
      }
    }, { wide: true, guardChanges:review, kind: 'skill',saveLabel:review?'保存草稿':'保存', successMessage:review?'技能草稿已保存，请提交审核': skill ? '技能已更新' : '技能已创建',
      afterSave:async()=>{await afterSave?.();if(review&&!draft)location.hash='#reviews'} })

  if(draft?.targetId)$('#skill-name').readOnly=true
  const renderResources = () => {
    for (const kind of Object.keys(resourceKinds)) {
      const list = $(`[data-resource-list="${kind}"]`, dialogContent)
      const existing = (current.resources || []).filter(resource => resource.kind === kind && !removedResources.has(resource.path) && !pendingResources.has(resource.path))
      const pending = [...pendingResources].filter(([path]) => path.startsWith(`${kind}/`))
      list.innerHTML = [
        ...existing.map(resource => `<div class="skill-resource-row"><a href="${draft ? '/api/reviews/'+draft.id+'/resources/'+resource.path.split('/').map(encodeURIComponent).join('/') : resourceUrl(skill?.id || current.name, resource.path)}" download>${escapeHtml(resource.path)}</a><span>${formatBytes(resource.size)}</span><button type="button" class="icon-button resource-remove" data-resource-path="${escapeHtml(resource.path)}" aria-label="删除 ${escapeHtml(resource.name)}">×</button></div>`),
        ...pending.map(([path, file]) => `<div class="skill-resource-row pending"><span>${escapeHtml(path)}</span><em>待上传 · ${formatBytes(file.size)}</em><button type="button" class="icon-button resource-remove" data-resource-path="${escapeHtml(path)}" aria-label="取消上传 ${escapeHtml(file.name)}">×</button></div>`),
      ].join('') || '<p class="skill-resource-empty">暂无文件</p>'
    }
    applyPermissions(dialogContent)
    $$('.resource-remove', dialogContent).forEach(button => button.onclick = () => {
      const path = button.dataset.resourcePath
      if (pendingResources.has(path)) pendingResources.delete(path)
      else removedResources.add(path)
      dialogContent.dispatchEvent(new Event('input',{bubbles:true}))
      renderResources()
    })
  }
  $$('[data-resource-input]', dialogContent).forEach(input => input.onchange = () => {
    const kind = input.dataset.resourceInput
    for (const file of input.files || []) {
      if (file.name.startsWith('.')) { toast('不能上传隐藏文件', true); continue }
      const path = `${kind}/${file.name}`
      pendingResources.set(path, file)
      removedResources.delete(path)
    }
    input.value = ''
    renderResources()
  })
  renderResources()
}
