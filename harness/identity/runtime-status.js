/* randomUUID fallback: intranet HTTP is not a secure context */
if (globalThis.crypto?.getRandomValues && !crypto.randomUUID) crypto.randomUUID = function () {
  var b = crypto.getRandomValues(new Uint8Array(16)); b[6] = b[6] & 15 | 64; b[8] = b[8] & 63 | 128;
  var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1) }).join('');
  return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
};
// Served only after the gateway authenticates a user and selects their private Host.
// Native DSH otherwise makes public-origin settings memory-only. This documented
// client transport hook enables the native personal settings UI, not server privileges.
// The gateway still checks every RPC, company scope, preset, path and credential ref.
(() => {
  const send = globalThis.fetch.bind(globalThis);
  globalThis.__DSH_TRANSPORT__ = Object.freeze({
    ownsHost: true,
    fetch(input, init) {
      const target = new URL(input, location.href);
      if (target.origin !== location.origin || !(target.pathname.startsWith('/api/') || target.pathname.startsWith((globalThis.departmentScope?.[0] || '/')+'api/'))) {
        return Promise.reject(new Error('Personal Harness RPC must use its authenticated gateway'));
      }
      return send(target, { ...init, credentials: 'same-origin', redirect: 'error' });
    },
  });
})();

// A reclaimed instance stays stopped until the user explicitly reopens it.
// Never reload automatically: preserve any unsent composer input in the page.
addEventListener('DOMContentLoaded',()=>{
  let notice;
  async function check(){
    try{
      const response=await fetch(new URL('runtime-status', document.baseURI),{method:'POST',signal:AbortSignal.timeout(10000)});
      const state=await response.json();
      if(response.ok&&state.ready){if(notice){notice.remove();notice=null;}return;}
      if(!notice){
        notice=document.createElement('aside');notice.setAttribute('role','status');
        notice.style.cssText='position:fixed;top:12px;left:12px;right:12px;z-index:2147483647;padding:16px;background:#fff6df;color:#573f00;border:1px solid #d9b868;border-radius:12px;font:14px system-ui';
        const message=document.createElement('span');
        message.textContent=response.ok?'个人 AI 已空闲回收，会话和设置已保留。请先复制未发送的文字，再重新打开。':'个人 AI 连接或授权已变化，请先保留未发送文字，再从部门系统重新打开。';
        const link=document.createElement('a');link.href=new URL('starting', document.baseURI);link.textContent='重新打开';link.style.marginLeft='16px';
        notice.append(message,link);document.body.append(notice);
      }
    }catch{/* A network interruption is not evidence that the instance was reclaimed. */}
  }
  setInterval(check,15000);
});

