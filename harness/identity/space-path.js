// The gateway binds this document to one authenticated user and space.
(() => {
  const [base, user] = window.departmentScope;
  const namespace = user + ':' + base + ':';
  for (const name of ['localStorage', 'sessionStorage']) {
    const storage = window[name];
    const keys = () => Object.keys(storage).filter(k => k.startsWith(namespace));
    const scoped = {
      get length() { return keys().length; },
      key(i) { return keys()[i]?.slice(namespace.length) ?? null; },
      getItem(k) { return storage.getItem(namespace + k); },
      setItem(k, v) { storage.setItem(namespace + k, v); },
      removeItem(k) { storage.removeItem(namespace + k); },
      clear() { for (const k of keys()) storage.removeItem(k); }
    };
    Object.defineProperty(window, name, { value: scoped });
  }
  function route(input) {
    const url = new URL(input, document.baseURI);
    if (url.host === location.host && url.pathname.startsWith('/s/') && !url.pathname.startsWith(base)) {
      throw new Error('AI 请求的公司空间与当前标签页不一致');
    }
    if (url.host === location.host && /^\/(api|assets|plugins|modules)\//.test(url.pathname)) {
      url.pathname = base + url.pathname.slice(1);
    }
    return url;
  }
  const send = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (input instanceof Request) {
      const url = route(input.url);
      return send(url.href === input.url ? input : new Request(url, input), init);
    }
    return send(route(input), init);
  };
  const Socket = window.WebSocket;
  window.WebSocket = class extends Socket {
    constructor(url, ...args) { super(route(url), ...args); }
  };
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (link) link.href = route(link.href).href;
  }, true);
})();
