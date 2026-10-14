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
s=s.replace('finally:\n    if proc:', '''except Exception:
    import traceback
    traceback.print_exc()
    for label, cmd, path in [('voice','meeting-state','/tmp/wizard-mvp-qa-meeting.json'),('authority','native-authority-state','/tmp/wizard-mvp-qa-authority.json'),('dom','eval JSON.stringify({url:location.href,orb:window.qaOrb,voice:window.WizVoice?.status?.(),capture:window.WizAppCapture?.state?.(),draft:document.querySelector(".chat-compose textarea")?.value})','/tmp/wizard-mvp-qa-eval.txt')]:
        try:
            qa(cmd);time.sleep(.3)
            result=Path(path).read_text();(OUT/('failure-'+label+'.json')).write_text(result);print('FAILURE_DIAGNOSTIC',label,result,flush=True)
        except Exception as exc:print('DIAGNOSTIC_FAILED',label,str(exc),flush=True)
    raise
finally:
    if proc:''')
assert 'FAILURE_DIAGNOSTIC' in s, 'diagnostic insertion did not match frozen harness'
exec(compile(s,str(p),'exec'))
