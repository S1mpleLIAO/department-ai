// A reclaimed instance stays stopped until the user explicitly reopens it.
// Never reload automatically: preserve any unsent composer input in the page.
addEventListener('DOMContentLoaded',()=>{
  let notice;
  async function check(){
    try{
      const response=await fetch('/runtime-status',{method:'POST',signal:AbortSignal.timeout(10000)});
      const state=await response.json();
      if(response.ok&&state.ready){if(notice){notice.remove();notice=null;}return;}
      if(!notice){
        notice=document.createElement('aside');notice.setAttribute('role','status');
        notice.style.cssText='position:fixed;top:12px;left:12px;right:12px;z-index:2147483647;padding:16px;background:#fff6df;color:#573f00;border:1px solid #d9b868;border-radius:12px;font:14px system-ui';
        const message=document.createElement('span');
        message.textContent=response.ok?'个人 AI 已空闲回收，会话和设置已保留。请先复制未发送的文字，再重新打开。':'个人 AI 连接或授权已变化，请先保留未发送文字，再从部门系统重新打开。';
        const link=document.createElement('a');link.href='/starting';link.textContent='重新打开';link.style.marginLeft='16px';
        notice.append(message,link);document.body.append(notice);
      }
    }catch{/* A network interruption is not evidence that the instance was reclaimed. */}
  }
  setInterval(check,15000);
});

