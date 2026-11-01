// Renders the macOS app icon from the same composition as the Wizard OS PWA icon
// (wizard-ux tools/brand/render-pwa-icons.cjs: Void background, dot grid, UV glow, white->UV hat),
// placed on Apple's app-icon grid: an 824/1024 rounded tile with a soft shadow, transparent outside.
// Usage (repo root): NODE_PATH=<dir with playwright> WIZARD_ICON_BROWSER=/usr/bin/chromium node next/mac/assets/render-mac-icon.cjs
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path'); const crypto = require('crypto');
const BRAND = path.join(__dirname, 'brand');
const mark = 'data:image/png;base64,' + fs.readFileSync(path.join(BRAND, 'wizard-mark-white.png')).toString('base64');
const SIZES = [16, 32, 48, 64, 128, 180, 192, 256, 512, 1024];
const html = `<html><body style="margin:0"><canvas id=c></canvas><script>
const UV='#7A5CFF', VOID='#0B0A10';
function rr(x,a,b,w,h,r){x.beginPath();x.moveTo(a+r,b);x.arcTo(a+w,b,a+w,b+h,r);x.arcTo(a+w,b+h,a,b+h,r);x.arcTo(a,b+h,a,b,r);x.arcTo(a,b,a+w,b,r);x.closePath();}
// Same tile as the PWA icon (full-bleed square), drawn at T pixels.
async function tile(T,small){const im=new Image();im.src='${mark}';await im.decode();
 const c=document.createElement('canvas');c.width=c.height=T;const x=c.getContext('2d');
 x.fillStyle=VOID;x.fillRect(0,0,T,T);
 if(T>=96){const g=T/16;x.fillStyle='rgba(122,92,255,0.22)';for(let i=1;i<16;i++)for(let j=1;j<16;j++){x.beginPath();x.arc(i*g,j*g,Math.max(0.8,T/420),0,7);x.fill();}}
 const rg=x.createRadialGradient(T*.5,T*.56,0,T*.5,T*.56,T*.48);rg.addColorStop(0,'rgba(122,92,255,0.45)');rg.addColorStop(1,'rgba(122,92,255,0)');x.fillStyle=rg;x.fillRect(0,0,T,T);
 const mh=T*(small?0.74:0.56), mw=mh*im.width/im.height, mx=(T-mw)/2, my=(T-mh)/2+T*0.01;
 const o=document.createElement('canvas');o.width=o.height=T;const ox=o.getContext('2d');ox.drawImage(im,mx,my,mw,mh);ox.globalCompositeOperation='source-in';
 const lg=ox.createLinearGradient(0,my,0,my+mh);lg.addColorStop(0,'#FFFFFF');lg.addColorStop(1,UV);ox.fillStyle=small?UV:lg;ox.fillRect(0,0,T,T);
 x.drawImage(o,0,0);return c;}
window.macIcon=async(S)=>{
 const c=document.getElementById('c');c.width=c.height=S;const x=c.getContext('2d');x.clearRect(0,0,S,S);
 const small=S<=32, T=Math.round(S*824/1024), off=(S-T)/2, r=T*0.225;
 const t=await tile(T,small);
 if(S>=64){x.save();x.shadowColor='rgba(0,0,0,0.30)';x.shadowBlur=S*0.02;x.shadowOffsetY=S*0.01;rr(x,off,off,T,T,r);x.fillStyle=VOID;x.fill();x.restore();}
 x.save();rr(x,off,off,T,T,r);x.clip();x.drawImage(t,off,off);x.restore();
 return c.toDataURL('image/png');};
</script></body></html>`;
(async () => {
  const b = await chromium.launch(process.env.WIZARD_ICON_BROWSER ? { executablePath: process.env.WIZARD_ICON_BROWSER } : { channel: 'chrome' });
  const p = await b.newPage(); await p.setContent(html);
  const prov = JSON.parse(fs.readFileSync(path.join(BRAND, 'provenance.json')));
  for (const S of SIZES) {
    const d = await p.evaluate(S => macIcon(S), S); const buf = Buffer.from(d.split(',')[1], 'base64');
    const name = 'wizard-icon-' + S + '.png'; fs.writeFileSync(path.join(BRAND, name), buf);
    prov.generated_sha256[name] = crypto.createHash('sha256').update(buf).digest('hex');
  }
  await b.close();
  fs.writeFileSync(path.join(BRAND, 'provenance.json'), JSON.stringify(prov, null, 2) + '\n'); console.log('MAC_ICON_OK');
})();
