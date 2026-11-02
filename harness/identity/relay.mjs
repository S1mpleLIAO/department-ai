// Private container transport. The host alone holds the other end of these sockets.
import http from 'node:http';
import fs from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {WebSocket,WebSocketServer} from '/opt/harness/packages/api/gateway/node_modules/ws/wrapper.mjs';
let launchToken='', cookie='', refreshing;
const child=spawn('/usr/local/bin/node',['--expose-internals','--import','/integration/model-fetch.mjs','--import','/opt/harness/node_modules/tsx/dist/esm/index.mjs',
  '/opt/harness/apps/cli/src/bin.ts','--profile','web','--patch','/config/patch.yml','--no-open','--port','39080'],
  {stdio:['ignore','pipe','pipe']});
function logLine(text){
  const token=text.match(/dsh web: http:\/\/127\.0\.0\.1:39080\/\?token=([^\s]+)/);
  if(token)launchToken=token[1];
  process.stderr.write(text.replace(/([?]token=)[^\s]+/g,'$1[REDACTED]'));
}
for(const stream of [child.stdout,child.stderr]){
  let pending='';
  stream.setEncoding('utf8');
  stream.on('data',data=>{
    pending+=data;
    let end;
    while((end=pending.indexOf('\n'))>=0){logLine(pending.slice(0,end+1));pending=pending.slice(end+1);}
  });
  stream.on('end',()=>{if(pending)logLine(pending);});
}
child.on('exit',()=>process.exit(1));
async function auth(){
  if(refreshing)return refreshing;
  refreshing=(async()=>{
    if(!launchToken)throw Error('starting');
    const probe=await fetch('http://127.0.0.1:39080/',{headers:{Cookie:cookie},redirect:'manual'});
    await probe.body?.cancel();
    if(probe.status===200)return;
    if(probe.status!==401)throw Error('upstream unavailable');
    const r=await fetch('http://127.0.0.1:39080/?token='+encodeURIComponent(launchToken),{redirect:'manual'});
    if(r.status!==303)throw Error('authentication failed');
    cookie=(r.headers.get('set-cookie')||'').split(';')[0]; await r.body?.cancel();
  })();
  try{await refreshing;}finally{refreshing=undefined;}
}
const server=http.createServer(async(req,res)=>{
  try{
    await auth();
    if(req.url==='/__ready'){res.writeHead(200);res.end('ready');return;}
    if(req.url?.startsWith('/api/file?')){
      const requested=new URL(req.url,'http://local').searchParams.get('path');
      let real,stat;
      try{real=await fs.realpath(requested||'');stat=await fs.stat(real);}
      catch{res.writeHead(404);res.end('File not found');return;}
      if(!real.startsWith('/home/assistant/workspace/') || !stat.isFile()){
        res.writeHead(403);res.end('File access denied');return;
      }
      if(stat.size>20*1024*1024){res.writeHead(413);res.end('File too large');return;}
    }
    const headers={...req.headers,host:'127.0.0.1:39080',origin:'http://127.0.0.1:39080',cookie};
    delete headers.authorization;
    const upstream=http.request({hostname:'127.0.0.1',port:39080,path:req.url,method:req.method,headers},response=>{
      const safe={...response.headers}; delete safe['set-cookie']; delete safe.location;
      res.writeHead(response.statusCode,safe);response.pipe(res);
    });
    upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502);res.end('AI transport unavailable');});
    req.pipe(upstream);
  }catch{res.writeHead(503);res.end('AI runtime is starting or unavailable');}
});
const wsServer=new WebSocketServer({noServer:true,maxPayload:1024*1024});
server.on('upgrade',async(req,socket,head)=>{
  if(req.url!=='/api/remote.mux'){socket.destroy();return;}
  try{await auth();}catch{socket.destroy();return;}
  const upstream=new WebSocket('ws://127.0.0.1:39080/api/remote.mux',{headers:{Cookie:cookie,Origin:'http://127.0.0.1:39080'}});
  upstream.on('open',()=>wsServer.handleUpgrade(req,socket,head,client=>{
    client.on('message',data=>upstream.send(data.toString()));
    upstream.on('message',data=>client.send(data.toString()));
    client.on('close',()=>upstream.close());upstream.on('close',()=>client.close());
    client.on('error',()=>upstream.close());upstream.on('error',()=>client.close());
  }));
  upstream.on('error',()=>socket.destroy());
});
await fs.rm('/transport/web.sock',{force:true});
server.listen('/transport/web.sock',()=>fs.chmod('/transport/web.sock',0o600));
// The only model/tool egress is this socket. No TCP network leaves the container.
http.createServer((req,res)=>{
  const upstream=http.request({socketPath:'/bridge/io.sock',path:req.url,method:req.method,
    headers:Object.fromEntries(Object.entries(req.headers).filter(([k])=>!['host','cookie','connection','content-length','transfer-encoding'].includes(k)))},r=>{
    res.writeHead(r.statusCode,r.headers);r.pipe(res);
  });
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(503);res.end();});
  req.on('aborted',()=>upstream.destroy());req.pipe(upstream);
}).listen(39100,'127.0.0.1');
