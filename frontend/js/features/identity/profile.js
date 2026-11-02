import { $, escapeHtml as e } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { identity } from '../../core/session.js'
import { openDialog, dialogContent, confirmAction } from '../../ui/dialog.js'
import { toast } from '../../ui/feedback.js'
import { passwordField, bindPasswordControls } from './auth.js'

export async function renderProfile() {
  const host=$('#content')
  host.innerHTML='<div class="loading" role="status">正在加载个人信息…</div>'
  try {
    const sessions=await request('/api/me/sessions')
    const info=await request('/api/me')
    if(location.hash!=='#profile' || !identity)return
    host.innerHTML=`<div class="identity-profile"><section class="panel"><h2>${e(info.user.displayName)}</h2><p>${e(info.user.username)} · ${e(info.companyName)}</p><p>${info.user.superadmin?'超级管理员':info.spaces.map(s=>e(s.name)).join(' · ')}</p><div class="actions"><button class="button" id="edit-profile">修改姓名</button><button class="button" id="change-password">修改密码</button></div></section>
      <section class="panel"><h2>当前授权</h2>${info.user.superadmin?'<p>全部公司、部门共享及系统管理权限。</p>':info.spaces.map(s=>`<details><summary>${e(s.name)}</summary><p>${(info.permissions[s.id]||[]).map(e).join('、')||'暂无操作权限'}</p></details>`).join('')}</section>
      <section class="panel"><h2>登录设备</h2><p>退出设备会立即撤销该登录会话。</p>${sessions.items.map(s=>`<div class="identity-session"><div><strong>${s.id===sessions.currentId?'当前设备':'其他设备'}</strong><p>${e(s.user_agent||'未知设备')}</p><small>最近访问：${new Date(s.last_seen_at).toLocaleString('zh-CN')}</small></div><button class="button small" data-revoke="${s.id}">退出设备</button></div>`).join('')}</section></div>`
    $('#edit-profile').onclick=()=>openDialog('修改姓名','姓名用于显示操作记录。',`<div class="field"><label for="profile-name">姓名</label><input id="profile-name" value="${e(info.user.displayName)}" maxlength="64" required></div>`,()=>request('/api/me',{method:'PATCH',body:{displayName:$('#profile-name').value}}),{afterSave:()=>location.reload()})
    $('#change-password').onclick=()=>{
      openDialog('修改密码','新密码至少12个字符。修改后将退出全部设备，需要重新登录。',passwordField('profile-old','当前密码')+passwordField('profile-new','新密码','new-password'),async()=>{
        await request('/api/me/password',{method:'POST',body:{currentPassword:$('#profile-old').value,password:$('#profile-new').value}})
      },{afterSave:()=>location.reload()})
      bindPasswordControls(dialogContent)
    }
    host.querySelectorAll('[data-revoke]').forEach(button=>button.onclick=async()=>{
      try {
        if(!await confirmAction('退出这个登录设备？','该设备需要重新输入密码登录。',{confirmLabel:'退出设备'}))return
        button.disabled=true
        await request('/api/me/sessions/'+button.dataset.revoke,{method:'DELETE'})
        if(button.dataset.revoke===sessions.currentId)location.reload()
        else await renderProfile()
      }catch(error){toast(error.message,true);button.disabled=false}
    })
  }catch(error){host.innerHTML=`<div class="empty" role="alert">${e(error.message)}</div>`}
}

