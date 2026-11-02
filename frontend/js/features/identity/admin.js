import { $, $$, escapeHtml as e } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { identity } from '../../core/session.js'
import { confirmAction, dialogContent, openDialog } from '../../ui/dialog.js'
import { toast, setAction } from '../../ui/feedback.js'
import { bindPasswordControls, passwordField } from './auth.js'
import { bindPermissionTree, permissionTree } from './permissions.js'
import { renderSettings } from '../settings.js'

let data = null
let tab = 'users'
let userPage = 0
let groupPage = 0
let groupSearch = ''
let generation = 0
let focusTab = false
const content = $('#content')
const field = (id,label,value='',type='text') => `<div class="field"><label for="${id}">${label}</label><input id="${id}" type="${type}" value="${e(value)}" maxlength="64" required></div>`
const companySelect = (value='zkxk') => `<div class="field"><label for="user-company">所属公司</label><select id="user-company">${data.companies.map(c=>`<option value="${c.id}" ${c.id===value?'selected':''}>${e(c.name)}</option>`).join('')}</select></div>`
const confirmChange = (message,detail) => confirmAction(message,detail,{confirmLabel:'确认修改'})
function afterSave() { return renderAdmin() }

export async function renderAdmin() {
  const renderId=++generation
  if (!identity?.user.superadmin) {content.innerHTML='<div class="empty">没有系统管理权限</div>';return}
  tab = location.hash === '#settings' ? 'settings' : tab === 'settings' ? 'users' : tab
  const route = location.hash
  setAction('',null)
  content.innerHTML='<div class="loading" role="status">正在加载系统管理…</div>'
  try {
    if(tab!=='settings') data=await request('/api/admin/overview?page='+userPage)
    if(renderId!==generation || location.hash!==route)return
    content.innerHTML=`<section class="identity-admin"><div class="identity-tabs" role="tablist" aria-label="系统管理">${[['users','用户管理'],['groups','权限组管理'],['companies','公司管理'],['audit','操作记录'],['settings','系统设置']].map(([key,label])=>`<button type="button" id="admin-tab-${key}" aria-controls="admin-panel" class="button ${tab===key?'primary':''}" role="tab" aria-selected="${tab===key}" data-admin-tab="${key}">${label}</button>`).join('')}</div><div id="admin-panel" role="tabpanel" aria-labelledby="admin-tab-${tab}"></div></section>`
    const tabs=$$('[data-admin-tab]')
    tabs.forEach((b,index)=>{
      b.tabIndex=b.dataset.adminTab===tab?0:-1
      b.onclick=()=>{
        tab=b.dataset.adminTab
        focusTab=true
        const destination=tab==='settings'?'#settings':'#admin'
        if(location.hash!==destination) location.hash=destination
        else void renderAdmin()
      }
      b.onkeydown=event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
        event.preventDefault()
        const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length
        tabs[next].click()
      }
    })
    if(tab==='settings') renderSettings(renderAdmin, $('#admin-panel'))
    else if(tab==='users') renderUsers()
    else if(tab==='groups') renderGroups()
    else if(tab==='companies') renderCompanies()
    else await renderAudit()
    if(renderId===generation && location.hash===route && focusTab) {
      $('#admin-tab-'+tab)?.focus()
      focusTab=false
    }
  } catch(error) {
    if(renderId!==generation || location.hash!==route)return
    content.innerHTML=`<div class="empty" role="alert">${e(error.message)} <button class="button" id="retry-admin">重试</button></div>`
    $('#retry-admin').onclick=()=>void renderAdmin()
  }
}

function renderUsers() {
  $('#admin-panel').innerHTML=`<div class="panel-heading"><div><h2>用户管理</h2><p>所属公司决定默认授权；跨公司范围由超级管理员单独分配。</p></div><button class="button primary" id="create-user">新建用户</button></div>
    <div class="table-wrap"><table><thead><tr><th>用户</th><th>公司</th><th>状态</th><th>权限</th><th>操作</th></tr></thead><tbody>${data.users.map(u=>`<tr><td><strong>${e(u.displayName)}</strong><small>${e(u.username)}</small></td><td>${e(data.companies.find(c=>c.id===u.companyId)?.name||'')}</td><td>${u.active?'正常':'已停用'}${u.mustChangePassword?' · 待改密':''}</td><td>${u.superadmin?'超级管理员':data.grants.filter(g=>g.user_id===u.id).map(g=>e(data.spaces.find(s=>s.id===g.space_id)?.name)+' / '+e(data.groups.find(p=>p.id===g.group_id)?.name)).join('<br>')||'尚未授权'}</td><td><div class="actions"><button class="button small" data-user-edit="${u.id}">编辑</button><button class="button small" data-user-grants="${u.id}" ${u.superadmin?'disabled':''}>授权</button><button class="button small" data-user-reset="${u.id}">重置密码</button></div></td></tr>`).join('')}</tbody></table></div>`
  $('#admin-panel').insertAdjacentHTML('beforeend',`<div class="identity-pagination"><span>共 ${data.userTotal} 位用户 · 第 ${userPage+1} 页</span><button class="button small" id="users-prev" ${userPage===0?'disabled':''}>上一页</button><button class="button small" id="users-next" ${(userPage+1)*data.pageSize>=data.userTotal?'disabled':''}>下一页</button></div>`)
  $('#users-prev').onclick=()=>{userPage--;void renderAdmin()}
  $('#users-next').onclick=()=>{userPage++;void renderAdmin()}
  $('#create-user').onclick=()=>userEditor()
  $$('[data-user-edit]').forEach(b=>b.onclick=()=>userEditor(data.users.find(u=>u.id===b.dataset.userEdit)))
  $$('[data-user-grants]').forEach(b=>b.onclick=()=>grantEditor(data.users.find(u=>u.id===b.dataset.userGrants)))
  $$('[data-user-reset]').forEach(b=>b.onclick=()=>resetPassword(data.users.find(u=>u.id===b.dataset.userReset)))
}
function userEditor(user) {
  openDialog(user?'编辑用户':'新建用户',user?'修改状态、公司或管理员身份后，该用户需要重新登录。':'初始密码至少12个字符，首次登录必须修改。',`
    <div class="form-grid">${!user?field('user-name','用户名'):''}${field('user-display','姓名',user?.displayName)}${companySelect(user?.companyId)}
    ${!user?passwordField('user-password','初始密码','new-password'):`<label class="checkbox"><input id="user-active" type="checkbox" ${user.active?'checked':''}>启用账号</label><label class="checkbox"><input id="user-superadmin" type="checkbox" ${user.superadmin?'checked':''}>超级管理员（拥有全部公司及系统权限）</label>`}</div>`,async()=>{
      if(user) {
        if(!await confirmChange('确认修改用户「'+user.displayName+'」？','公司变更会移除原公司授权；状态或管理员身份变更立即生效。'))return false
        await request('/api/admin/users/'+user.id,{method:'PUT',body:{displayName:$('#user-display').value,companyId:$('#user-company').value,active:$('#user-active').checked,superadmin:$('#user-superadmin').checked,revision:user.revision}})
      } else {
        await request('/api/admin/users',{method:'POST',body:{username:$('#user-name').value,displayName:$('#user-display').value,companyId:$('#user-company').value,password:$('#user-password').value}})
        userPage=0
      }
    },{afterSave})
  bindPasswordControls(dialogContent)
}
function resetPassword(user) {
  openDialog('重置密码：'+user.displayName,'全部旧登录会话会失效。请通过受控渠道将初始密码交给本人。',passwordField('reset-password','新初始密码','new-password'),async()=>{
    if(!await confirmChange('重置「'+user.displayName+'」的密码？','该用户将退出全部设备，下次登录必须修改密码。'))return false
    await request('/api/admin/users/'+user.id+'/reset-password',{method:'POST',body:{password:$('#reset-password').value}})
  },{afterSave})
  bindPasswordControls(dialogContent)
}
function grantEditor(user) {
  const selected=new Map(data.spaces.map(s=>[s.id,new Set(data.grants.filter(g=>g.user_id===user.id&&g.space_id===s.id).map(g=>g.group_id))]))
  const original=new Map([...selected].map(([id,groups])=>[id,new Set(groups)]))
  openDialog('分配权限组：'+user.displayName,'权限组决定能做什么；生效范围决定在哪家公司能做。切换范围本身不会新增授权。',`
    <div class="field"><label for="grant-scope">生效范围</label><select id="grant-scope">${data.spaces.map(s=>`<option value="${e(s.id)}" ${s.id===user.companyId?'selected':''}>${e(s.name)}</option>`).join('')}</select></div>
    <p id="grant-summary" role="status"></p><div class="grant-columns"><section><h3>选择权限组</h3><div class="field"><label for="grant-search">查找权限组</label><input type="search" id="grant-search" placeholder="输入权限组名称"></div><div class="identity-grants" id="grant-groups"></div></section><section><h3>当前范围的生效功能</h3><p>以下为所选权限组的合并结果。修改功能请到“权限组管理”。</p><div id="grant-effective"></div></section></div>`,async()=>{
      const grants=[...selected].flatMap(([spaceId,groups])=>[...groups].map(groupId=>({spaceId,groupId})))
      const added=data.spaces.filter(s=>s.id!==user.companyId&&s.id!=='shared'&&[...selected.get(s.id)].some(g=>!original.get(s.id).has(g)))
      const detail=(added.length?'将新增跨公司授权：'+added.map(s=>s.name).join('、')+'。':'')+'未选中的原授权将撤销，新权限在下一次请求生效。'
      if(!await confirmChange('更新「'+user.displayName+'」的授权？',detail))return false
      await request('/api/admin/users/'+user.id+'/grants',{method:'PUT',body:{grants,revision:user.revision}})
    },{afterSave,wide:true,guardChanges:true})
  function effective() {
    const scope=$('#grant-scope').value, ids=selected.get(scope)
    const actions=[...new Set(data.groups.filter(g=>ids.has(g.id)).flatMap(g=>g.actions))]
    $('#grant-effective').innerHTML=actions.length?permissionTree(data.actions,actions,true):'<p class="empty">此范围尚未授予任何功能。</p>'
    $('#grant-summary').textContent=data.spaces.map(s=>`${s.name}：${selected.get(s.id).size} 个权限组`).join('；')
  }
  function groups() {
    const ids=selected.get($('#grant-scope').value), query=$('#grant-search').value.trim().toLowerCase()
    $('#grant-groups').innerHTML=data.groups.filter(g=>(g.name+' '+g.description).toLowerCase().includes(query)).map(g=>`<label class="grant-option"><input type="checkbox" data-grant-group="${e(g.id)}" ${ids.has(g.id)?'checked':''}><span><strong>${e(g.name)}</strong><small>${e(g.description||'未填写说明')} · ${g.actions.length} 项功能</small></span></label>`).join('')||'<p class="empty">没有匹配的权限组</p>'
    $$('[data-grant-group]',dialogContent).forEach(input=>input.onchange=()=>{input.checked?ids.add(input.dataset.grantGroup):ids.delete(input.dataset.grantGroup);effective()})
    effective()
  }
  // Browsing/filtering scopes is not an unsaved permission change.
  $('#grant-scope').oninput=event=>event.stopPropagation()
  $('#grant-scope').onchange=event=>{event.stopPropagation();groups()}
  $('#grant-search').oninput=event=>{event.stopPropagation();groups()}
  $('#grant-search').onchange=event=>event.stopPropagation()
  groups()
}
function renderGroups() {
  const matches=data.groups.filter(g=>(g.name+' '+g.description).toLowerCase().includes(groupSearch.toLowerCase()))
  groupPage=Math.min(groupPage,Math.max(0,Math.ceil(matches.length/10)-1))
  $('#admin-panel').innerHTML=`<div class="panel-heading"><div><h2>权限组管理</h2><p>按业务模块配置操作权限，再将权限组分配给用户及公司范围。修改内容不等于免审核发布。</p></div><button class="button primary" id="create-group">新建权限组</button></div>
    <form id="group-search-form" class="identity-group-search"><div class="field"><label for="group-search">查找权限组</label><input type="search" id="group-search" value="${e(groupSearch)}" placeholder="名称或说明"></div><button class="button" type="submit">查找</button></form>
    <div class="process-list">${matches.slice(groupPage*10,groupPage*10+10).map(g=>`<article class="panel"><div class="item-head"><div><h3>${e(g.name)}</h3><p>${e(g.description)}</p><small>${g.actions.length} 项功能 · ${new Set(data.grants.filter(x=>x.group_id===g.id).map(x=>x.user_id)).size} 位成员</small></div><div class="actions"><button class="button small" data-group-edit="${g.id}">配置功能</button><button class="button small" data-group-members="${g.id}">成员</button><button class="button small" data-group-copy="${g.id}">复制</button><button class="button small danger" data-group-delete="${g.id}" ${['members','readers'].includes(g.id)?'disabled':''}>删除</button></div></div></article>`).join('')||'<p class="empty">没有匹配的权限组</p>'}</div>
    <div class="identity-pagination"><span>共 ${matches.length} 个权限组 · 第 ${groupPage+1} 页</span><button class="button small" id="groups-prev" ${groupPage===0?'disabled':''}>上一页</button><button class="button small" id="groups-next" ${(groupPage+1)*10>=matches.length?'disabled':''}>下一页</button></div>`
  $('#group-search-form').onsubmit=event=>{event.preventDefault();groupSearch=$('#group-search').value.trim();groupPage=0;renderGroups();$('#group-search').focus()}
  $('#groups-prev').onclick=()=>{groupPage--;renderGroups()}
  $('#groups-next').onclick=()=>{groupPage++;renderGroups()}
  $('#create-group').onclick=()=>groupEditor()
  $$('[data-group-edit]').forEach(b=>b.onclick=()=>groupEditor(data.groups.find(g=>g.id===b.dataset.groupEdit)))
  $$('[data-group-copy]').forEach(b=>b.onclick=()=>groupEditor({...data.groups.find(g=>g.id===b.dataset.groupCopy),id:null,revision:null,name:'复制的权限组'}))
  $$('[data-group-members]').forEach(b=>b.onclick=()=>groupMembers(data.groups.find(g=>g.id===b.dataset.groupMembers)))
  $$('[data-group-delete]').forEach(b=>b.onclick=async()=>{try{
    const g=data.groups.find(g=>g.id===b.dataset.groupDelete)
    if(!await confirmAction('删除权限组「'+g.name+'」？','仍有成员使用时不能删除。'))return
    await request('/api/admin/permission-groups/'+g.id,{method:'DELETE'});await renderAdmin();toast('权限组已删除')
  }catch(error){toast(error.message,true)}})
}
function groupEditor(group) {
  const affected=data.grants.filter(g=>g.group_id===group?.id)
  openDialog(group?.id?'配置功能：'+group.name:'新建权限组','按模块勾选功能。使用技能不授予源码访问；免审核直接发布需单独勾选。',`
    ${field('group-name','权限组名称',group?.name)}<div class="field"><label for="group-description">说明</label><textarea id="group-description" maxlength="255">${e(group?.description||'')}</textarea></div>
    <p>影响范围：${new Set(affected.map(g=>g.user_id)).size} 位成员，${new Set(affected.map(g=>g.space_id)).size} 个空间</p>
    ${permissionTree(data.actions,group?.actions)}`,async()=>{
      if(!await confirmChange('保存权限组设置？','保存后，所有使用此组的成员立即按新的权限访问系统。'))return false
      const body={name:$('#group-name').value,description:$('#group-description').value,actions:$$('[data-action-module]:checked',dialogContent).map(x=>x.value)}
      if(group?.id)body.revision=group.revision
      await request('/api/admin/permission-groups'+(group?.id?'/'+group.id:''),{method:group?.id?'PUT':'POST',body})
    },{afterSave,wide:true,guardChanges:true})
  bindPermissionTree(dialogContent)
}

function renderCompanies() {
  $('#admin-panel').innerHTML=`<h2>公司管理</h2><p>成员所属公司用于初始授权。跨公司能力由用户的权限组授权决定。</p><div class="process-list">${data.companies.map(c=>`<article class="panel"><h3>${e(c.name)}</h3><p>独立管理本公司知识、业务流程和技能。</p></article>`).join('')}<article class="panel"><h3>部门共享</h3><p>存放两家公司共用的已发布资料。新成员默认获得共享只读权限；维护、审核和发布需要单独授权。</p></article></div>`
}

function groupMembers(group) {
  let page=0, loadId=0
  openDialog('权限组成员：'+group.name,'同一成员在不同空间的授权分别显示。', '<div id="group-members-list"></div>',null,{wide:true,readOnly:true})
  const host=$('#group-members-list')
  async function load() {
    const id=++loadId
    host.innerHTML='<p role="status">正在加载成员…</p>'
    try {
      const result=await request('/api/admin/permission-groups/'+group.id+'/members?page='+page)
      if(!host.isConnected||id!==loadId)return
      host.innerHTML=result.items.map(u=>`<p><strong>${e(u.display_name)}</strong> · ${e(u.username)}<br><small>${e(u.space_name)}</small></p>`).join('')||'<p class="empty">此权限组尚未分配给成员</p>'
      host.insertAdjacentHTML('beforeend',`<div class="identity-pagination"><span>共 ${result.total} 项授权</span><button type="button" class="button small" data-member-prev ${page===0?'disabled':''}>上一页</button><button type="button" class="button small" data-member-next ${(page+1)*25>=result.total?'disabled':''}>下一页</button></div>`)
      host.querySelector('[data-member-prev]').onclick=()=>{page--;void load()}
      host.querySelector('[data-member-next]').onclick=()=>{page++;void load()}
    }catch(error){if(host.isConnected)host.innerHTML=`<p role="alert">${e(error.message)}</p><button type="button" class="button" id="retry-members">重试</button>`;host.querySelector('#retry-members')?.addEventListener('click',()=>void load())}
  }
  void load()
}
async function renderAudit(before=null) {
  const result=await request('/api/admin/audit'+(before?'?before='+before:''))
  if(location.hash!=='#admin' || tab!=='audit')return
  $('#admin-panel').innerHTML=`<h2>操作记录</h2><p>仅记录操作对象与身份，不记录密码或文件正文。</p><div class="table-wrap"><table><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>对象</th></tr></thead><tbody>${result.items.map(x=>`<tr><td>${new Date(x.created_at).toLocaleString('zh-CN')}</td><td>${e(x.display_name||'系统')}</td><td>${e(x.action)}</td><td>${e(x.target_id)}</td></tr>`).join('')}</tbody></table></div>${result.items.length===50?'<button class="button" id="older-audit">查看更早记录</button>':''}`
  if($('#older-audit'))$('#older-audit').onclick=()=>void renderAudit(result.items.at(-1).id).catch(error=>toast(error.message,true))
}

