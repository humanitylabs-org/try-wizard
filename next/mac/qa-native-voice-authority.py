#!/usr/bin/env python3
"""Run frozen voice regression, collecting exact native/DOM failure diagnostics."""
from pathlib import Path
p=Path(__file__).with_name('qa-native-voice-shortcut.py')
s=p.read_text()
s=s.replace('finally:\n    if app:', '''except Exception:
    import traceback
    traceback.print_exc()
    for label, cmd, path in [('voice','voice-native-state','/tmp/wizard-mvp-qa-voice.json'),('authority','native-authority-state','/tmp/wizard-mvp-qa-authority.json'),('dom','eval JSON.stringify({url:location.href,orb:window.qaOrb,voice:window.WizVoice?.status?.(),capture:window.WizAppCapture?.state?.(),draft:document.querySelector(".chat-compose textarea")?.value})','/tmp/wizard-mvp-qa-eval.txt')]:
        try:
            qa(cmd);time.sleep(.3)
            result=Path(path).read_text();(OUT/('failure-'+label+'.json')).write_text(result);print('FAILURE_DIAGNOSTIC',label,result,flush=True)
        except Exception as exc:print('DIAGNOSTIC_FAILED',label,str(exc),flush=True)
    raise
finally:
    if app:''')
exec(compile(s,str(p),'exec'))
