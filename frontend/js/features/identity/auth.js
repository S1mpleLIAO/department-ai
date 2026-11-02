import { $, escapeHtml } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { clearIdentity, identity, setIdentity, spaceId, pageAllowed } from '../../core/session.js'
import { replaceState } from '../../core/state.js'
import { confirmAction } from '../../ui/dialog.js'

const shell = $('.app-shell')
const host = $('#auth-host')
let restart = null

export function passwordField(id, label, autocomplete = 'current-password') {
  return `<div class="field"><label for="${id}">${label}</label><div class="password-control"><input id="${id}" name="${id}" type="password" autocomplete="${autocomplete}" maxlength="128" required><button type="button" class="button small" data-toggle-password="${id}" aria-label="显示${label}" aria-pressed="false">显示</button></div></div>`
}
export function bindPasswordControls(root) {
  root.querySelectorAll('[data-toggle-password]').forEach(button => button.onclick = () => {
    const input = document.getElementById(button.dataset.togglePassword)
    const visible = input.type === 'password'
    input.type = visible ? 'text' : 'password'
    button.textContent = visible ? '隐藏' : '显示'
    button.setAttribute('aria-pressed', String(visible))
    button.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码')
  })
}
function showLogin(message = '') {
  clearIdentity()
  replaceState({processes:[],documents:[],skills:[],categories:[],purposes:[],settings:null,services:{}})
  document.querySelectorAll('dialog[open]').forEach(d => d.close())
  $('#content').replaceChildren()
  $('#assistant-host').replaceChildren()
  shell.hidden = true
  host.hidden = false
  host.innerHTML = `<form class="identity-login panel" id="login-form" novalidate>
    <div class="brand-mark">AI</div><h1>登录部门 AI</h1><p>使用部门账号访问公司知识与业务流程</p>
    <div class="field"><label for="login-username">用户名</label><input id="login-username" name="username" autocomplete="username" maxlength="64" required></div>
    ${passwordField('login-password','密码')}
    <p id="login-error" class="identity-error" role="alert">${escapeHtml(message)}</p>
    <button class="button primary" type="submit">登录</button><small>账号由管理员开通；忘记密码请联系管理员。</small></form>`
  bindPasswordControls(host)
  const form = $('#login-form'), button = form.querySelector('[type=submit]')
  form.onsubmit = async event => {
    event.preventDefault()
    if (button.disabled || event.isComposing) return
    const username = $('#login-username').value.trim(), password = $('#login-password').value
    if (!username || !password) { $('#login-error').textContent = '请填写用户名和密码'; (!username ? $('#login-username') : $('#login-password')).focus(); return }
    button.disabled = true; button.setAttribute('aria-busy','true')
    try {
      await request('/api/auth/login', {method:'POST',body:{username,password}})
      await restart()
    } catch (error) { $('#login-error').textContent = error.message; $('#login-password').value = ''; $('#login-password').focus() }
    finally { button.disabled = false; button.removeAttribute('aria-busy') }
  }
  $('#login-username').focus()
}
function forcePassword() {
  shell.hidden = true; host.hidden = false
  host.innerHTML = `<form class="identity-login panel" id="first-password" novalidate><h1>设置个人密码</h1><p>首次登录或密码重置后，请先修改密码。新密码为12至128个字符。</p>
    ${passwordField('old-password','当前密码')}${passwordField('new-password','新密码','new-password')}
    <p class="identity-error" id="password-error" role="alert"></p><button class="button primary" type="submit">修改密码并重新登录</button><button type="button" class="button" id="first-logout">退出登录</button></form>`
  bindPasswordControls(host)
  $('#first-logout').onclick = logout
  $('#first-password').onsubmit = async e => {
    e.preventDefault(); const button=e.currentTarget.querySelector('[type=submit]')
    if(button.disabled) return
    const password=$('#new-password').value
    if(password.length<12) {$('#password-error').textContent='新密码至少12个字符';$('#new-password').focus();return}
    button.disabled=true
    try { await request('/api/me/password',{method:'POST',body:{currentPassword:$('#old-password').value,password}});showLogin('密码已修改，请重新登录') }
    catch(error) {const status=$('#password-error');if(status)status.textContent=error.message}
    finally {button.disabled=false}
  }
}
export async function logout() {
  try { await request('/api/auth/logout',{method:'POST'}); showLogin('已退出登录') }
  catch(error) { const status=$('#identity-status') || $('#password-error'); if(status) status.textContent=error.message }
}
export async function initializeIdentity(start) {
  restart=start
  try {
    const value=await request('/api/me')
    setIdentity(value)
    if(value.user.mustChangePassword) {forcePassword();return false}
    host.hidden=true;host.replaceChildren();shell.hidden=false
    $('#identity-controls').innerHTML=`<label for="space-switch">当前空间</label><select id="space-switch">${value.spaces.map(s=>`<option value="${escapeHtml(s.id)}" ${s.id===spaceId?'selected':''}>${escapeHtml(s.name)}</option>`).join('')}</select>
      <a class="button small" href="#profile">${escapeHtml(value.user.displayName)}</a><button class="button small" id="logout">退出</button><small id="identity-status" role="status"></small>`
    $('#logout').onclick=logout
    $('#space-switch').onchange=async event=>{
      const next=event.target.value
      if(document.querySelector('dialog[open]') && !await confirmAction('切换空间？','未保存的编辑将丢失。',{confirmLabel:'切换空间'})){event.target.value=spaceId;return}
      sessionStorage.setItem('department-space',next)
      location.reload()
    }
    document.querySelectorAll('#navigation [data-page]').forEach(a => {a.hidden=!pageAllowed(a.dataset.page)})
    return true
  } catch(error) {
    showLogin(error.status===401 ? '' : '暂时无法连接系统，请重试')
    return false
  }
}
window.addEventListener('identity-expired',()=>showLogin('登录已失效，请重新登录'))

