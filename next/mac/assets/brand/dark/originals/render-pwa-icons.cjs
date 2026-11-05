// Renders the Wizard OS PWA icons from the supplied designer hat (web/brand/wizard-mark-white.png).
// Usage (repo root): node tools/brand/render-pwa-icons.cjs  -> web/icon-512.png, icon-192.png, apple-touch-icon.png, favicon.ico
const { chromium } = require('playwright'); const fs=require('fs'); const path=require('path');
const ROOT=path.join(__dirname,'..','..'), WEB=path.join(ROOT,'web');
const mark='data:image/png;base64,'+fs.readFileSync(path.join(WEB,'brand','wizard-mark-white.png')).toString('base64');
const html=`<html><body style="margin:0;background:transparent"><canvas id=c></canvas><script>
const UV='#7A5CFF', VOID='#0B0A10', ETCH='#1D1A24';
function rr(x,a,b,w,h,r){x.beginPath();x.moveTo(a+r,b);x.arcTo(a+w,b,a+w,b+h,r);x.arcTo(a+w,b+h,a,b+h,r);x.arcTo(a,b+h,a,b,r);x.arcTo(a,b,a+w,b,r);x.closePath();}
window.draw=async(S,opts)=>{const im=new Image();im.src='${mark}';await im.decode();
 const c=document.getElementById('c');c.width=c.height=S;const x=c.getContext('2d');x.clearRect(0,0,S,S);
 const full=opts.full; // full-bleed square (maskable/apple) vs rounded tile (favicon)
 if(opts.layer!=='foreground' && opts.layer!=='monochrome') {
 if(full){x.fillStyle=VOID;x.fillRect(0,0,S,S)}else{rr(x,0,0,S,S,S*0.22);x.fillStyle=VOID;x.fill();}
 x.save(); if(!full){rr(x,0,0,S,S,S*0.22);x.clip();}
 // experimental: faint dotted lab grid + UV glow behind the mark
 if(S>=96||opts.forceGrid){const g=S/16;x.fillStyle='rgba(122,92,255,0.22)';for(let i=1;i<16;i++)for(let j=1;j<16;j++){x.beginPath();x.arc(i*g,j*g,Math.max(0.8,S/420),0,7);x.fill();}}
 const rg=x.createRadialGradient(S*.5,S*.56,0,S*.5,S*.56,S*.48);rg.addColorStop(0,'rgba(122,92,255,0.45)');rg.addColorStop(1,'rgba(122,92,255,0)');x.fillStyle=rg;x.fillRect(0,0,S,S);
 // diagonal UV "test" band in the top-right corner (inside maskable safe area edge)
 x.restore();
 }
 // mark: UV->white gradient, scaled into safe zone
 if(opts.layer!=='background') {
 const mh=S*(opts.small?0.74:0.56), mw=mh*im.width/im.height, mx=(S-mw)/2, my=(S-mh)/2+S*0.01;
 const o=document.createElement('canvas');o.width=o.height=S;const ox=o.getContext('2d');ox.drawImage(im,mx,my,mw,mh);ox.globalCompositeOperation='source-in';
 const lg=ox.createLinearGradient(0,my,0,my+mh);lg.addColorStop(0,'#FFFFFF');lg.addColorStop(1,UV);ox.fillStyle=opts.layer==='monochrome'?'#FFFFFF':opts.small?UV:lg;ox.fillRect(0,0,S,S);
 x.drawImage(o,0,0);
 // badge: small UV pill dot at upper-right = "lab" marker
 if(false){const r=S*0.075, cx=S*0.73, cy=S*0.27;x.beginPath();x.arc(cx,cy,r,0,7);x.fillStyle=UV;x.fill();x.lineWidth=S*0.018;x.strokeStyle=VOID;x.stroke();}
 }
 return c.toDataURL('image/png');};
// 108dp adaptive layers frame the same 72dp composition as the PWA.
// Hat ink is 40.32dp high, wholly within Android's 66dp safe circle.
window.nativeLayer=async(S,layer)=>{
 const im=new Image();im.src=await draw(S*72/108,{full:true,layer,forceGrid:true});await im.decode();
 const c=document.createElement('canvas');c.width=c.height=S;const x=c.getContext('2d');
 if(layer==='background'){x.fillStyle=VOID;x.fillRect(0,0,S,S);}
 x.drawImage(im,S/6,S/6);return c.toDataURL('image/png');
};
window.round=async(S)=>{
 const im=new Image();im.src=await draw(S,{full:true});await im.decode();
 const c=document.createElement('canvas');c.width=c.height=S;const x=c.getContext('2d');
 x.beginPath();x.arc(S/2,S/2,S/2,0,Math.PI*2);x.clip();x.drawImage(im,0,0);return c.toDataURL('image/png');
};
window.previewSheet=async()=>{
 const layers=[];for(const layer of ['background','foreground']){const im=new Image();im.src=await nativeLayer(648,layer);await im.decode();layers.push(im);}
 const c=document.createElement('canvas');c.width=1080;c.height=500;const x=c.getContext('2d');x.fillStyle='#17151E';x.fillRect(0,0,1080,500);
 x.fillStyle='#FFFFFF';x.font='24px sans-serif';x.fillText('Void launcher · Android masked viewport',36,46);
 for(let i=0;i<3;i++){const a=60+i*350,b=105,s=260;x.save();
 if(i===0){x.beginPath();x.arc(a+s/2,b+s/2,s/2,0,Math.PI*2);}
 else if(i===1){x.beginPath();for(let t=0;t<=Math.PI*2+.01;t+=.01){const u=Math.cos(t),v=Math.sin(t),px=a+s/2+s/2*Math.sign(u)*Math.sqrt(Math.abs(u)),py=b+s/2+s/2*Math.sign(v)*Math.sqrt(Math.abs(v));if(t===0)x.moveTo(px,py);else x.lineTo(px,py);}x.closePath();}
 else rr(x,a,b,s,s,s*.22);
 x.clip();for(const im of layers)x.drawImage(im,108,108,432,432,a,b,s,s);x.restore();
 x.fillStyle='#FFFFFF';x.font='21px sans-serif';x.fillText(['Circle','Squircle','Rounded square'][i],a,410);}
 x.fillStyle='#BEB6D8';x.font='18px sans-serif';x.fillText('Supplied hat · shared PWA compositor · 40.32dp hat inside 66dp safe zone',36,468);
 return c.toDataURL('image/png');
};
</script></body></html>`;
// Native: add --android [--preview /path/to/preview.png]. WIZARD_ICON_BROWSER may select a local Chromium executable.
(async()=>{const b=await chromium.launch(process.env.WIZARD_ICON_BROWSER?{executablePath:process.env.WIZARD_ICON_BROWSER}:{channel:'chrome'});const p=await b.newPage();await p.setContent(html);
if(process.argv.includes('--android')){
 try {
 const res=path.join(ROOT,'android/app/src/main/res');
 const save=(name,data)=>{fs.mkdirSync(path.dirname(name),{recursive:true});fs.writeFileSync(name,Buffer.from(data.split(',')[1],'base64'));};
 for(const [density,factor] of [['mdpi',1],['hdpi',1.5],['xhdpi',2],['xxhdpi',3],['xxxhdpi',4]]){
 const dir=path.join(res,'mipmap-'+density);
 save(path.join(dir,'ic_launcher.png'),await p.evaluate(S=>draw(S,{full:true}),48*factor));
 save(path.join(dir,'ic_launcher_round.png'),await p.evaluate(S=>round(S),48*factor));
 for(const layer of ['background','foreground','monochrome'])save(path.join(dir,'ic_launcher_'+layer+'.png'),await p.evaluate(([S,L])=>nativeLayer(S,L),[108*factor,layer]));
 }
 for(const name of ['ic_launcher','ic_launcher_round'])for(const [dir,mono] of [['mipmap-anydpi',false],['mipmap-anydpi-v33',true]]){
 const xml='<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n    <background android:drawable="@mipmap/ic_launcher_background" />\n    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'+(mono?'    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />\n':'')+'</adaptive-icon>\n';
 fs.mkdirSync(path.join(res,dir),{recursive:true});fs.writeFileSync(path.join(res,dir,name+'.xml'),xml);
 }
 const idx=process.argv.indexOf('--preview');if(idx>=0){if(!process.argv[idx+1])throw Error('--preview requires a path');save(path.resolve(process.argv[idx+1]),await p.evaluate(()=>previewSheet()));}
 console.log('Native Void icon layers, legacy and round variants rendered');
 }finally{await b.close();}
 return;
}
const out={};const jobs=[['icon-512.png',512,{full:true}],['icon-192.png',192,{full:true}],['apple-touch-icon.png',180,{full:true}],['fav-64.png',64,{small:true}],['fav-32.png',32,{small:true}],['fav-16.png',16,{small:true}]];
for(const [n,S,o] of jobs){const d=await p.evaluate(([S,o])=>draw(S,o),[S,o]);out[n]=(Buffer.from(d.split(',')[1],'base64'));}
await b.close();
for(const n of ['icon-512.png','icon-192.png','apple-touch-icon.png'])fs.writeFileSync(path.join(WEB,n),out[n]);
// favicon.ico: PNG-in-ICO with 16/32/64 frames
const fr=['fav-16.png','fav-32.png','fav-64.png'].map(n=>out[n]),sz=[16,32,64];const h=Buffer.alloc(6+16*fr.length);h.writeUInt16LE(0,0);h.writeUInt16LE(1,2);h.writeUInt16LE(fr.length,4);let off=h.length;fr.forEach((b,i)=>{const e=6+16*i;h.writeUInt8(sz[i]%256,e);h.writeUInt8(sz[i]%256,e+1);h.writeUInt16LE(1,e+4);h.writeUInt16LE(32,e+6);h.writeUInt32LE(b.length,e+8);h.writeUInt32LE(off,e+12);off+=b.length;});
fs.writeFileSync(path.join(WEB,'favicon.ico'),Buffer.concat([h,...fr]));console.log('ok')})();
