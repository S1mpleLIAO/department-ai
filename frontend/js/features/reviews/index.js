import { $, $$, escapeHtml as e } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { can,identity,fileUrl,spaceId } from '../../core/session.js'
import { replaceState,state } from '../../core/state.js'
import { formatDate } from '../../core/format.js'
import { openDialog,confirmAction } from '../../ui/dialog.js'
import { toast,setAction } from '../../ui/feedback.js'
import { editDraft } from './edit-entry.js'

const names={processes:'业务流程',knowledge:'知识文档',skills:'技能'}
const statuses={draft:'草稿',submitted:'待审核',rejected:'已驳回',approved:'待发布',publish_failed:'发布失败',published:'已发布'}
let page=0, mode='mine',generation=0,detailGeneration=0
const content=$('#content')

export async function renderReviews() {
  const current=++generation, space=spaceId
  setAction('',null)
  content.innerHTML='<div class="loading" role="status">正在加载提交记录…</div>'
  try {
    const data=await request('/api/reviews?mode='+mode+'&page='+page)
    if(current!==generation||space!==spaceId||location.hash!=='#reviews')return
    page=data.page
    content.innerHTML=`<section class="review-page"><div class="panel-heading"><div><h2>当前空间的提交记录</h2><p>草稿仅作者与审核员可见；通过审核后，由有发布权限的管理员发布。</p></div><div class="field"><label for="review-mode">查看范围</label><select id="review-mode"><option value="mine">我的提交</option><option value="pending">待我处理</option><option value="all">全部可见</option></select></div></div>
      <div class="table-wrap"><table><thead><tr><th>名称 / 类型</th><th>提交人</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${data.items.map(row=>`<tr><td><b>${e(row.title)}</b><small>${names[row.kind]} · ${row.targetId?'修改':'新增'} · ${row.version?'第 '+row.version+' 次提交':'尚未提交'}</small></td><td>${e(row.author)}</td><td><span class="tag">${statuses[row.status]}</span>${row.feedback?'<p>'+e(row.feedback)+'</p>':''}${row.publish_error?'<p class="identity-error">'+e(row.publish_error)+'</p>':''}</td><td>${formatDate(row.updatedAt)}</td><td><button class="button small" data-review-id="${e(row.id)}">查看</button></td></tr>`).join('')||'<tr><td colspan="5"><div class="empty">没有符合条件的提交。可从流程、知识库或技能页面新增草稿。</div></td></tr>'}</tbody></table></div>
      <div class="identity-pagination"><span>共 ${data.total} 条 · 第 ${page+1} 页</span><button class="button" id="review-prev" ${page===0?'disabled':''}>上一页</button><button class="button" id="review-next" ${(page+1)*20>=data.total?'disabled':''}>下一页</button></div></section>`
    $('#review-mode').value=mode
    $('#review-mode').onchange=()=>{mode=$('#review-mode').value;page=0;void renderReviews()}
    $('#review-prev').onclick=()=>{page--;void renderReviews()}
    $('#review-next').onclick=()=>{page++;void renderReviews()}
    $$('[data-review-id]').forEach(b=>b.onclick=()=>void showDetail(b.dataset.reviewId))
  } catch(error) {
    if(current!==generation||location.hash!=='#reviews')return
    content.innerHTML=`<div class="empty" role="alert">加载失败：${e(error.message)}<p><button class="button" id="review-retry">重试</button></p></div>`
    $('#review-retry').onclick=()=>void renderReviews()
  }
}

function preview(row) {
  const d=row.data
  if(row.kind==='processes')return `<p>${e(d.description)}</p><ol>${d.steps.map(s=>`<li><h3>${e(s.name)}</h3><p>${e(s.objective)}</p>${[['输入',s.requiredInputs],['交付物',s.requiredOutputs],['完成标准',s.completionCriteria]].map(([name,items])=>'<b>'+name+'</b><ul>'+items.map(v=>'<li>'+e(v)+'</li>').join('')+'</ul>').join('')}<pre class="identity-source">${e(s.instructions)}</pre></li>`).join('')}</ol>`
  if(row.kind==='skills')return `<p>${e(d.skill.description)}</p><p>发布后：${d.skill.enabled?'启用':'停用'}</p><pre class="identity-source">${e(d.skill.instructions)}</pre><h3>附件（仅查看，不执行）</h3><ul>${d.resources.map(r=>'<li><a download href="'+fileUrl('/api/reviews/'+row.id+'/resources/'+r.path.split('/').map(encodeURIComponent).join('/')+(row.isBase?'?version=base':''))+'">'+e(r.path)+'</a></li>').join('')||'<li>无附件</li>'}</ul>`
  const m={...d.metadata,
    purposeId:state.purposes.find(item=>item.id===d.metadata.purposeId)?.name||d.metadata.purposeId,
    categoryId:state.categories.find(item=>item.id===d.metadata.categoryId)?.name||d.metadata.categoryId}
  return `<p><a class="button" download href="${fileUrl('/api/reviews/'+row.id+'/source')}">下载原文：${e(d.fileName)}</a></p><dl class="review-metadata">${[['标题',m.title],['用途',m.purposeId],['目录',m.categoryId||'未分类'],['文档类型',m.documentType],['关键词',(m.keywords||[]).join('、')],['文档简介',m.summary],['模板家族',m.templateFamily],['变体',m.templateVariant],['版本',m.version],['适用场景',m.applicableScenario]].map(([label,value])=>'<dt>'+label+'</dt><dd>'+e(value||'—')+'</dd>').join('')}</dl><details><summary>查看解析正文</summary><pre class="identity-source">${e(d.parsedText)}</pre></details><h3>拟发布分块</h3>${(m.chunks||[]).map((c,i)=>'<details><summary>分块 '+(i+1)+' · '+(c.enabled?'使用':'不使用')+'</summary><pre class="identity-source">'+e(c.content)+'</pre></details>').join('')||'<p>此文档不需要正文分块</p>'}`
}

async function showDetail(id) {
  const current=++detailGeneration
  const space=spaceId, user=identity?.user.id
  try {
    const row=await request('/api/reviews/'+id)
    if(current!==detailGeneration||space!==spaceId||user!==identity?.user.id||location.hash!=='#reviews')return
    const mine=row.owner_id===user
    const editable=mine&&['draft','rejected'].includes(row.status)&&can(row.kind+(row.targetId?'.edit_any':'.create'))
    const reviewable=!mine&&can(row.kind+'.review')
    const controls=[
      editable?'<button class="button" data-review-action="edit">修改草稿</button><button class="button primary" data-review-action="submit">提交审核</button>':'',
      reviewable&&row.status==='submitted'?'<button class="button primary" data-review-action="approve">通过审核</button>':'',
      reviewable&&['submitted','approved','publish_failed'].includes(row.status)?'<button class="button" data-review-action="reject">驳回</button>':'',
      can(row.kind+'.publish')&&['approved','publish_failed'].includes(row.status)?'<button class="button primary" data-review-action="publish">'+(row.status==='publish_failed'?'重试发布':'发布')+'</button>':''
    ].join('')
    const dialog=openDialog(row.title,names[row.kind]+' · '+statuses[row.status]+' · '+(row.version?'第 '+row.version+' 次提交':'尚未提交'),
      `<div class="review-detail"><p>提交人：${e(row.author)}</p>${row.feedback?'<p class="review-feedback">审核意见：'+e(row.feedback)+'</p>':''}${row.publish_error?'<p role="alert" class="identity-error">'+e(row.publish_error)+'</p>':''}${row.base?'<p class="review-feedback">这是修改稿。正式版本在审核发布前保持不变；如正式资料已变化，请重新起草。</p><details><summary>修改前（起草时的正式版本）</summary>'+preview({...row,data:row.base,isBase:true})+'</details><h3>本次修改稿</h3>':''}${preview(row)}
      <p>历史提交：${row.history.map(v=>'第 '+v.number+' 次（'+formatDate(v.created_at)+'）').join('、')||'尚未提交'}</p>
      ${reviewable&&['submitted','approved','publish_failed'].includes(row.status)?'<div class="field"><label for="review-reason">审核意见（驳回必填）</label><textarea id="review-reason" maxlength="2000"></textarea></div>':''}
      <p id="review-error" class="identity-error" role="alert"></p><div class="actions">${controls}</div></div>`,async()=>{}, {wide:true,readOnly:true})
    $$('[data-review-action]').forEach(button=>button.onclick=async event=>{
      event.preventDefault()
      $('#review-error').textContent=''
      const action=button.dataset.reviewAction
      const reason=$('#review-reason')?.value.trim()||''
      if(action==='edit'){
        await dialog.close()
        editDraft(row,renderReviews)
        return
      }
      if(action==='reject'&&!reason){$('#review-error').textContent='请填写驳回原因';$('#review-reason').setAttribute('aria-invalid','true');$('#review-reason').setAttribute('aria-describedby','review-error');$('#review-reason').focus();return}
      const labels={submit:'提交审核',approve:'通过审核',reject:'驳回',publish:'发布'}
      const messages={submit:'提交后不能修改，审核员将审核这次提交的固定内容。',approve:'通过后进入待发布，尚不会出现在正式资料中。',reject:'作者可以修改后重新提交，当前内容不会发布。',publish:'发布到当前空间；知识文档将建立索引，可能需要一些时间。'}
      if(!await confirmAction(labels[action]+'“'+row.title+'”？',messages[action],{confirmLabel:labels[action],tone:action==='reject'?'danger':'primary'}))return
      const buttons=$$('[data-review-action]')
      buttons.forEach(b=>b.disabled=true)
      dialog.setBusy(true)
      button.setAttribute('aria-busy','true')
      try {
        const result=await request('/api/reviews/'+id+'/'+action,{method:'POST',body:{revision:row.revision,reason}})
        await dialog.close()
        replaceState(await request('/api/state'))
        await renderReviews()
        if(result.status==='publish_failed'){toast('发布未完成，错误信息已保留，可重试',true);await showDetail(id)}
        else toast({submit:'已提交审核',approve:'审核已通过，等待发布',reject:'已驳回',publish:'已发布'}[action])
      }catch(error){const target=$('#review-error');if(target)target.textContent=error.message+'。可关闭后重新查看最新状态。'}
      finally{dialog.setBusy(false);buttons.forEach(b=>b.disabled=false);button.removeAttribute('aria-busy')}
    })
    const reasonInput=$('#review-reason')
    if(reasonInput)reasonInput.oninput=()=>{reasonInput.removeAttribute('aria-invalid');reasonInput.removeAttribute('aria-describedby');$('#review-error').textContent=''}
  }catch(error){toast(error.message,true)}
}
