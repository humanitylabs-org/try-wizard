#!/usr/bin/env python3
"""Bounded AX inspection; optional previously authorized *owned* removable consent.
No loginwindow, Apple Events, settings automation, or broad permission grants.
The whole matching window must name the exact installed QA app. An Allow button
in another window is never eligible. Default is read-only. No GUI launch here.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess as sp


def eligible(rows, app_name):
    text = '\n'.join(str(r.get(k) or '') for r in rows for k in ('AXTitle','AXDescription','AXValue'))
    # Match the exact quoted app filename, not a similarly named app or generic Wizard.
    names = ('“'+app_name+'”', '"'+app_name+'"')
    return (any(n in text for n in names)
            and 'would like to access files on a removable volume' in text.lower()
            and sum(r.get('AXRole') == 'AXButton' and r.get('AXTitle') == 'Allow' for r in rows) == 1)


def command(pid):
    return sp.run(['/bin/ps','-p',str(pid),'-o','comm='],check=True,capture_output=True,text=True,timeout=3).stdout.strip()


def inspect(allow=False, requester=None, app_path=None, digest=None):
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    ax = C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    P = C.c_void_p
    def fn(lib, name, args, ret):
        f=getattr(lib,name); f.argtypes=args; f.restype=ret; return f
    trusted=fn(ax,'AXIsProcessTrusted',[],C.c_bool)
    assert trusted(), 'Existing AX authorization unavailable; do not request it'
    string=fn(cf,'CFStringCreateWithCString',[P,C.c_char_p,C.c_uint32],P)
    release=fn(cf,'CFRelease',[P],None); retain=fn(cf,'CFRetain',[P],P)
    equal=fn(cf,'CFEqual',[P,P],C.c_bool)
    get=fn(ax,'AXUIElementCopyAttributeValue',[P,P,C.POINTER(P)],C.c_int)
    create=fn(ax,'AXUIElementCreateApplication',[C.c_int],P)
    count=fn(cf,'CFArrayGetCount',[P],C.c_long); item=fn(cf,'CFArrayGetValueAtIndex',[P,C.c_long],P)
    tid=fn(cf,'CFGetTypeID',[P],C.c_ulong)
    array_type=fn(cf,'CFArrayGetTypeID',[],C.c_ulong); string_type=fn(cf,'CFStringGetTypeID',[],C.c_ulong)
    cstr=fn(cf,'CFStringGetCString',[P,P,C.c_long,C.c_uint32],C.c_bool)
    press=fn(ax,'AXUIElementPerformAction',[P,P],C.c_int)
    timeout=fn(ax,'AXUIElementSetMessagingTimeout',[P,C.c_float],C.c_int)
    def attr(el,name):
        k=string(None,name.encode(),0x08000100); v=P()
        err=get(el,k,C.byref(v));release(k)
        return v.value if err==0 else None
    def text(el,name):
        v=attr(el,name)
        if not v:return None
        try:
            if tid(v)!=string_type():return None
            b=C.create_string_buffer(8192)
            return b.value.decode() if cstr(v,b,len(b),0x08000100) else None
        finally:release(v)
    def children(el,name):
        v=attr(el,name)
        if not v:return []
        try:return [retain(item(v,i)) for i in range(min(count(v),100))] if tid(v)==array_type() else []
        finally:release(v)
    def check_requester():
        assert app_path and requester and digest
        p=Path(app_path)
        assert p.parent==Path('/Applications') and p.name.startswith('Wizard Native307 ')
        exe=p/'Contents/MacOS/Wizard'
        assert command(requester)==str(exe), 'Requester PID changed or foreign app'
        assert hashlib.sha256(exe.read_bytes()).hexdigest()==digest
    if allow:
        assert app_path is not None
        check_requester()
    app_name = Path(app_path).name if app_path else ''
    result={'pressed':False,'windows':[],'scope':'read-only' if not allow else 'exact owned QA removable-volume prompt only'}
    pids=sp.run(['/usr/bin/pgrep','-x','UserNotificationCenter'],capture_output=True,text=True,timeout=3).stdout.split()
    candidates=[]; retained=[]
    try:
        for pid in pids:
            assert command(int(pid))=='/System/Library/CoreServices/UserNotificationCenter.app/Contents/MacOS/UserNotificationCenter'
            root=create(int(pid));retained.append(root);timeout(root,1.0)
            windows=children(root,'AXWindows');retained.extend(windows)
            for window in windows:
                if text(window,'AXRole') not in ('AXWindow','AXSheet','AXDialog'):
                    continue  # Some locked-console AX providers return their application itself.
                rows=[];seen=[]; buttons=[]
                def walk(el,depth):
                    if depth>10 or len(seen)>=180 or any(equal(el,x) for x in seen):return
                    seen.append(retain(el)); retained.append(seen[-1])
                    row={k:text(el,k) for k in ('AXRole','AXTitle','AXDescription','AXValue')}
                    rows.append(row)
                    if row['AXRole']=='AXButton' and row['AXTitle']=='Allow':buttons.append(el)
                    kids=children(el,'AXChildren');retained.extend(kids)
                    for child in kids:walk(child,depth+1)
                walk(window,0)
                result['windows'].append({'pid':int(pid),'rows':rows})
                if allow and eligible(rows,app_name):candidates.append((int(pid),window,buttons[0]))
        if allow and len(candidates)==1:
            pid,window,button=candidates[0]
            check_requester()
            # Revalidate the window immediately; retained object identity binds the action.
            fresh=[];visited=[]
            def verify(el,depth=0):
                if depth>10 or len(visited)>=180 or any(equal(el,x) for x in visited):return
                visited.append(retain(el));retained.append(visited[-1])
                fresh.append({k:text(el,k) for k in ('AXRole','AXTitle','AXDescription','AXValue')})
                kids=children(el,'AXChildren');retained.extend(kids)
                for child in kids:verify(child,depth+1)
            verify(window)
            assert eligible(fresh,app_name) and text(button,'AXTitle')=='Allow'
            action=string(None,b'AXPress',0x08000100)
            try:err=press(button,action)
            finally:release(action)
            result.update(pressed=err==0,error=err,requesterPID=requester,app=str(app_path),notificationPID=pid)
            # Caller must verify actual IO/QA acknowledgment; AX success is not permission success.
        elif allow:result['reason']='No unique exact owned removable-volume window'
        return result
    finally:
        for el in reversed(retained):release(el)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--allow-owned-removable',action='store_true')
    ap.add_argument('--requester-pid',type=int);ap.add_argument('--app');ap.add_argument('--sha256')
    a=ap.parse_args()
    print(json.dumps(inspect(a.allow_owned_removable,a.requester_pid,a.app,a.sha256),ensure_ascii=False))

if __name__=='__main__':main()
