#!/usr/bin/env python3
"""Wizard Desktop edits to QEMU's ui/cocoa.m, applied after Try Omarchy's patches.

Makes the VM window behave like an ordinary Mac app window:
  * Cmd-Q, Cmd-H, Cmd-Option-H, Cmd-M, Cmd-Tab, Cmd-` and Ctrl-Cmd-F always go
    to macOS (quit, hide, minimise, switch apps, full screen) even while the
    focused guest owns the rest of the keyboard.
  * Ctrl-Cmd-F (the standard macOS chord) toggles full screen.
  * The window remembers its size and position, and has a sensible minimum.
  * Product strings say Wizard.
Fails loudly if the upstream source no longer matches, so a silent no-op can't ship.
"""
import re
import sys

path = sys.argv[1]
s = open(path, encoding="utf-8").read()


def sub(pattern, repl, expected, flags=0):
    global s
    new, n = re.subn(pattern, repl, s, flags=flags)
    if n != expected:
        sys.exit(f"wizard-cocoa-edit: expected {expected} match(es), got {n}: {pattern[:70]!r}")
    s = new


HELPER = r'''
/*
 * Wizard Desktop: these Command chords always belong to macOS so the window
 * behaves like any other Mac app, even while the focused guest owns the rest
 * of the keyboard: Cmd-Q quit, Cmd-H / Cmd-Opt-H hide, Cmd-M minimise,
 * Cmd-Tab and Cmd-` switch, Ctrl-Cmd-F full screen.
 */
static bool wizard_host_chord(NSEvent *event)
{
    if (!event) {
        return false;
    }
    NSEventType type = [event type];
    if (type != NSEventTypeKeyDown && type != NSEventTypeKeyUp) {
        return false;
    }
    NSEventModifierFlags modifiers = [event modifierFlags];
    if (!(modifiers & NSEventModifierFlagCommand)) {
        return false;
    }
    switch ([event keyCode]) {
    case kVK_ANSI_Q:
    case kVK_ANSI_H:
    case kVK_ANSI_M:
    case kVK_Tab:
    case kVK_ANSI_Grave:
        return true;
    case kVK_ANSI_F:
        return (modifiers & NSEventModifierFlagControl) != 0;
    default:
        return false;
    }
}

@implementation QemuCocoaView'''

# 1. helper, defined just before the view implementation
sub(r'\n@implementation QemuCocoaView', lambda m: HELPER, 1)

# 2. key down / key up: host chords stay with macOS even when the guest has the keyboard
sub(r'if \(!\[self isKeyboardCaptured\] &&(\s+)\(\[event modifierFlags\] & NSEventModifierFlagCommand\)\)',
    r'if ((![self isKeyboardCaptured] || wizard_host_chord(event)) &&\1([event modifierFlags] & NSEventModifierFlagCommand))',
    2)

# 3. standard macOS full-screen chord: Ctrl-Cmd-F
sub(r'(fullScreenMenuItem = \[\[\[NSMenuItem alloc\] initWithTitle:@"Enter Full Screen" action:@selector\(doToggleFullScreen:\) keyEquivalent:@"f"\] autorelease\];)',
    r'\1\n    [fullScreenMenuItem setKeyEquivalentModifierMask:(NSEventModifierFlagControl | NSEventModifierFlagCommand)];',
    1)

# 4. remember window size/position; keep the Wizard UI usable when shrunk
sub(r'(\[window makeKeyAndOrderFront:self\];\s*\n(\s*)\[window center\];)',
    r'\1\n\2[window setContentMinSize:NSMakeSize(720.0, 480.0)];\n\2[window setFrameAutosaveName:@"WizardMainWindow"];',
    1)

# 5. product name
n_before = s.count("Try Omarchy")
if n_before == 0:
    sys.exit("wizard-cocoa-edit: no product strings found")
s = s.replace("Try Omarchy", "Wizard")

open(path, "w", encoding="utf-8").write(s)
print(f"wizard-cocoa-edit: OK (host chords, Ctrl-Cmd-F, window memory, {n_before} product strings)")
