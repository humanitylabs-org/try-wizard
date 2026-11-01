// Two instances, each bound only to loopback on a random port. No real Wizard.
const http = require('node:http');
const label = process.argv[2] || 'Fixture';
const page = `<!doctype html><html data-shell><meta charset="utf-8"><title>${label}</title>
<style>body{background:${label==='One'?'#191628':'#edf2f8'};color:${label==='One'?'#eee':'#182034'};font:20px system-ui;padding:64px}input,button{font:inherit;padding:12px;margin:12px}pre{font-size:14px;white-space:pre-wrap}</style>
<h1>Wizard ${label} · native switcher fixture</h1><p>No VM or owner data. Separate loopback origin.</p>
<input id="draft" autocomplete="off" placeholder="A draft that must survive switching"><button id="counter" onclick="counter++;render()">Increment</button><pre id="receipt"></pre>
<script>
window.loadToken=crypto.randomUUID();window.counter=0;window.events=[];window.replies={};let sequence=0;
window.wizardNativeReply=m=>{replies[m.id]=m.result};
window.callNative=(method,params={})=>{const id='fixture-'+(++sequence);webkit.messageHandlers.wizardNative.postMessage({id,method,params});return id};
for(const name of ['workspaces','dictation','orb','key'])addEventListener('wizard:'+name,e=>{events.push({name,detail:e.detail});if(name==='orb')dispatchEvent(new CustomEvent('wizard:orb-state',{detail:{state:'fixture-handled'}}));render()});
// This assignment is what the injected native capability must survive.
window.wizardUX={events:['wizard:orb','wizard:dictation','wizard:key','wizard:open'],handle:(event,detail)=>['wizard:orb','wizard:dictation','wizard:key'].includes(event),fixture:'${label}'};
window.__wux={voice:'idle'};
function render(){document.querySelector('#receipt').textContent=JSON.stringify({label:'${label}',counter,loadToken,native:window.wizardUX.native,caps:window.wizardNativeCaps,events:events.slice(-8)},null,2)}render();
</script></html>`;
const server=http.createServer((req,res)=>{
  console.error(JSON.stringify({method:req.method,path:req.url,time:Date.now()}));
  res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});
  res.end(req.method==='HEAD'?'':page);
});
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({url:`http://127.0.0.1:${server.address().port}/`})));
process.on('SIGTERM',()=>server.close(()=>process.exit(0)));
