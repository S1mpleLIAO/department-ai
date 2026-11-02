// Native SDK URLs/keys stay in the personal DSH_HOME; no container TCP egress.
const nativeFetch=globalThis.fetch;
globalThis.fetch=async function(input,init){
  const request=new Request(input,init);
  const url=new URL(request.url);
  if(url.origin==='http://127.0.0.1:39100'||url.origin==='http://127.0.0.1:39080')
    return nativeFetch(request);
  const headers=new Headers(request.headers);
  headers.set('x-department-model-target',request.url);
  return nativeFetch('http://127.0.0.1:39100/personal-model',{
    method:request.method,headers,body:request.body,duplex:'half',signal:request.signal,redirect:'error',
  });
};
