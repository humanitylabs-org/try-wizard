#!/usr/bin/env python3
"""Run frozen voice regression, collecting exact native/DOM failure diagnostics."""
from pathlib import Path
p=Path(__file__).with_name('qa-native-voice-shortcut.py')
s=p.read_text()
# Orb replies are asynchronous even after the page reaches listening/idle.
# Preserve every frozen assertion, waiting for the exact claimed reply first.
for outcome in ['voice','sent']:
    original="    ok(voice()['orbTaps']==count+"+('1' if outcome=='voice' else '2')+" and ev('qaOrb.at(-1)')=='"+outcome+"'"
    replacement="    wait(lambda:ev('qaOrb.at(-1)')=='"+outcome+"',seconds=5)\n"+original
    assert original in s, 'frozen orb assertion changed'
    s=s.replace(original,replacement)
s=s.replace(
    "    initial=len(runs()); count=voice()['orbTaps']",
    "    ev(\"window.qaMediaCalls=0;const qaMedia=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async(...a)=>{qaMediaCalls++;return qaMedia(...a)},configurable:true});window.qaMediaProbe='pending';navigator.mediaDevices.getUserMedia({audio:true}).then(s=>{qaMediaProbe=s.getAudioTracks()[0].readyState;s.getTracks().forEach(t=>t.stop())}).catch(e=>qaMediaProbe=e.name);true\")\n    wait(lambda:ev('qaMediaProbe')=='live')\n    initial=len(runs()); count=voice()['orbTaps']"
)
s=s.replace('finally:\n    if proc:', '''except Exception:
    import traceback
    traceback.print_exc()
    for label, cmd, path in [('voice','meeting-state','/tmp/wizard-mvp-qa-meeting.json'),('authority','native-authority-state','/tmp/wizard-mvp-qa-authority.json'),('dom','eval JSON.stringify({url:location.href,orb:window.qaOrb,mediaCalls:window.qaMediaCalls,mediaProbe:window.qaMediaProbe,audioContext:window.qaAC?.state,ux:window.wizardUX,wuxVoice:window.__wux?.voice,errors:window.qaErrors,voice:window.WizVoice?.status?.(),capture:window.WizAppCapture?.state?.(),draft:document.querySelector(".chat-compose textarea")?.value})','/tmp/wizard-mvp-qa-eval.txt')]:
        try:
            qa(cmd);time.sleep(.3)
            result=Path(path).read_text();(OUT/('failure-'+label+'.json')).write_text(result);print('FAILURE_DIAGNOSTIC',label,result,flush=True)
        except Exception as exc:print('DIAGNOSTIC_FAILED',label,str(exc),flush=True)
    raise
finally:
    if proc:''')
assert 'FAILURE_DIAGNOSTIC' in s, 'diagnostic insertion did not match frozen harness'
exec(compile(s,str(p),'exec'))
