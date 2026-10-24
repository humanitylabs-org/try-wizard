#!/usr/bin/env python3
"""Press one exact button in one owned app using already-granted Accessibility.
Never targets loginwindow, changes permissions, or unlocks the console.
"""
import ctypes as C
import json
import sys


def main():
    pid, expected = int(sys.argv[1]), sys.argv[2]
    P = C.c_void_p
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    ax = C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    def fn(lib, name, args, ret):
        f = getattr(lib, name); f.argtypes = args; f.restype = ret; return f
    trusted = fn(ax, 'AXIsProcessTrusted', [], C.c_bool)
    if not trusted():
        print(json.dumps({'pressed': False, 'reason': 'existing Accessibility permission unavailable'})); return 2
    string = fn(cf, 'CFStringCreateWithCString', [P, C.c_char_p, C.c_uint32], P)
    release = fn(cf, 'CFRelease', [P], None)
    get = fn(ax, 'AXUIElementCopyAttributeValue', [P, P, C.POINTER(P)], C.c_int)
    app = fn(ax, 'AXUIElementCreateApplication', [C.c_int], P)
    count = fn(cf, 'CFArrayGetCount', [P], C.c_long)
    item = fn(cf, 'CFArrayGetValueAtIndex', [P, C.c_long], P)
    tid = fn(cf, 'CFGetTypeID', [P], C.c_ulong)
    array_type = fn(cf, 'CFArrayGetTypeID', [], C.c_ulong)
    string_type = fn(cf, 'CFStringGetTypeID', [], C.c_ulong)
    cstr = fn(cf, 'CFStringGetCString', [P, P, C.c_long, C.c_uint32], C.c_bool)
    retain = fn(cf, 'CFRetain', [P], P)
    press = fn(ax, 'AXUIElementPerformAction', [P, P], C.c_int)
    def attr(el, name):
        k = string(None, name.encode(), 0x08000100); v = P()
        error = get(el, k, C.byref(v)); release(k)
        return v.value if error == 0 else None
    def text_attr(el, name):
        v = attr(el, name)
        if not v: return None
        try:
            if tid(v) != string_type(): return None
            b = C.create_string_buffer(4096)
            return b.value.decode() if cstr(v, b, len(b), 0x08000100) else None
        finally: release(v)
    root = app(pid); matches = []; visited = 0
    def walk(el, depth):
        nonlocal visited
        visited += 1
        if visited > 350 or depth > 10: return
        if text_attr(el, 'AXRole') == 'AXButton' and text_attr(el, 'AXTitle') == expected:
            matches.append(retain(el))
        children = attr(el, 'AXChildren')
        if children:
            try:
                if tid(children) == array_type():
                    for i in range(count(children)): walk(item(children, i), depth + 1)
            finally: release(children)
    try:
        walk(root, 0)
        if len(matches) != 1:
            print(json.dumps({'pressed': False, 'matches': len(matches), 'pid': pid})); return 1
        action = string(None, b'AXPress', 0x08000100)
        try: error = press(matches[0], action)
        finally: release(action)
        print(json.dumps({'pressed': error == 0, 'error': error, 'pid': pid, 'button': expected}))
        return 0 if error == 0 else 1
    finally:
        for el in matches: release(el)
        release(root)


if __name__ == '__main__':
    raise SystemExit(main())
