#!/usr/bin/env python3
"""Narrow actual WK resize/capture facts; no acceptance assertions weakened."""
import pathlib
p=pathlib.Path(__file__).with_name('qa-combined-desktop.py')
s=p.read_text();prefix=s.split('try:\n    notifier=',1)[0];cleanup=s[s.rindex('finally:\n'):]
body='''try:
    notifier=OUT/'qa-post.swift'
    notifier.write_text('import Foundation\\nDistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"),object:CommandLine.arguments[1],userInfo:nil,deliverImmediately:true)\\nRunLoop.main.run(until:Date().addingTimeInterval(0.1))\\n')
    run('xcrun','swiftc','-O',notifier,'-o',OUT/'qa-post')
    for k in ['backends','activeBackend']:run('defaults','delete',DOMAIN,k,check=False)
    proc=sp.Popen([str(APP/'Contents/MacOS/Wizard'),'-QAHooks','YES','-QAWebStorage','YES','-DataHome',str(OUT/'data-home'),'-SUEnableAutomaticChecks','NO'],stdout=(OUT/'app.log').open('w'),stderr=sp.STDOUT)
    time.sleep(2);qa('voice-local-fixture '+URL);wait('!!window.__wux && !!window.__wux.live.ok')
    qa('voice-enable on')
    ev("window.qaResize=0;addEventListener('resize',()=>qaResize++);Object.values(__wux.wins).forEach(w=>__wux.closeWin(w.id));for(let i=0;i<4;i++)__wux.newWin({app:'chats'});__wux.focusWin(__wux.ws[0].wins[0]);true")
    def facts(label):
        out=json.loads(ev("JSON.stringify({inner:[innerWidth,innerHeight],resizeEvents:qaResize,stage:[document.querySelector('#stage').clientWidth,document.querySelector('#stage').clientHeight],workspace:[document.querySelector('.wsp:not([hidden])').clientWidth,document.querySelector('.wsp:not([hidden])').clientHeight],wins:[...document.querySelectorAll('.wsp:not([hidden]) .win')].map(e=>({style:e.style.cssText,rect:e.getBoundingClientRect().toJSON()}))})"))
        (OUT/(label+'.json')).write_text(json.dumps(out,indent=2));print(label,json.dumps(out),flush=True)
    for size in ['700x1000','1120x1000','380x560']:
        qa('window-size '+size);time.sleep(1);facts(size+'-native')
    qa('native-authority-state');time.sleep(.3);(OUT/'authority.json').write_text(pathlib.Path('/tmp/wizard-mvp-qa-authority.json').read_text())
    ev("window.dispatchEvent(new Event('resize'));true");time.sleep(.5);facts('380x560-manual-js-resize')
    # Isolate promise/stream behavior without acquiring any device.
    ev("window.qaPromise='pending';Promise.resolve(7).then(x=>qaPromise=x);window.qaStream='pending';const ac=new AudioContext();window.qaAC=ac;const d=ac.createMediaStreamDestination();window.qaDest=d;const o=ac.createOscillator();o.connect(d);o.start();ac.resume();window.qaClone=d.stream.clone();window.qaStream=qaClone.getAudioTracks().map(t=>t.readyState).join(',');window.qaAsync='pending';(async()=>d.stream.clone())().then(s=>qaAsync=s.getAudioTracks().map(t=>t.readyState).join(',')).catch(e=>qaAsync=String(e));true")
    time.sleep(1);facts('post-audio-generation')
    out=ev("JSON.stringify({promise:qaPromise,stream:qaStream,async:qaAsync,ac:qaAC.state,track:qaDest.stream.getAudioTracks().map(t=>({ready:t.readyState,enabled:t.enabled})),enabled:window.__wizardUpdateFrozen})")
    (OUT/'promise-stream.json').write_text(out);print('PROMISE_STREAM',out,flush=True)
'''
exec(compile(prefix+body+cleanup,str(p),'exec'))
