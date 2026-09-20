/* Streamlit's component protocol carries requests over its session WebSocket.
   The ordinary local-server interface continues to use fetch. */
(() => {
  if (window.parent === window || !location.pathname.includes('/component/')) return;
  let ready = false, active = null;
  const queue = [];
  const parentOrigin = new URL(document.referrer || location.href).origin;
  const send = (type, extra = {}) => window.parent.postMessage({isStreamlitMessage:true,type,...extra}, parentOrigin);
  const resize = () => send('streamlit:setFrameHeight', {height:Math.max(720, window.innerHeight)});
  function next() {
    if (!ready || active || !queue.length) return;
    active = queue.shift();
    send('streamlit:setComponentValue', {value:active.request, dataType:'json'});
  }
  window.fairrouteTransport = (path, body) => new Promise((resolve, reject) => {
    queue.push({request:{id:crypto.randomUUID(),path,body},resolve,reject});
    next();
  });
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== parentOrigin || event.data?.type !== 'streamlit:render') return;
    ready = true;
    const response = event.data.args?.response;
    if (active && response?.id === active.request.id) {
      const completed = active; active = null;
      if (response.error) completed.reject(Error(response.error));
      else completed.resolve(response.data);
    }
    resize(); next();
  });
  window.addEventListener('resize', resize);
  send('streamlit:componentReady', {apiVersion:1});
  resize();
})();
