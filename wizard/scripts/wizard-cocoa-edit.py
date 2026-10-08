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

# 4. remember window size/position. Small enough for a phone-shaped window; a
#    remembered frame below the minimum (e.g. from an older build) is replaced
#    by the default size. "WizardWindow" deliberately ignores 0.1.1's saved frame.
sub(r'(\[window makeKeyAndOrderFront:self\];\s*\n(\s*)\[window center\];)',
    r'\1\n\2[window setContentMinSize:NSMakeSize(520.0, 480.0)];'
    r'\n\2[window setFrameAutosaveName:@"WizardWindow"];'
    r'\n\2if (NSWidth([window contentRectForFrameRect:[window frame]]) < 520.0 ||'
    r'\n\2    NSHeight([window contentRectForFrameRect:[window frame]]) < 480.0) {'
    r'\n\2    [window setFrame:[window frameRectForContentRect:cocoa_initial_window_frame()] display:YES];'
    r'\n\2}',
    1)

# 9. tell the guest the real window size as soon as events are allowed. Stock
#    QEMU only sends it on the first user resize, so the Wizard first drew at
#    1920x1080 and was scaled down into the window.
sub(r'(- \(void\)applicationDidFinishLaunching: \(NSNotification \*\) note\n\{\n.*?\n(\s*)allow_events = true;\n)',
    r'\1\2[cocoaView updateScale];\n\2[cocoaView updateUIInfo];\n', 1, flags=re.S)

# 6. free resizing: the guest display follows the window (Try Omarchy's dynamic
#    display), so the window is never locked to the guest's aspect ratio and is
#    never shrunk to the guest's pixel size (that is what opened it tiny on Retina).
RESIZE = r'''- (void) resizeWindow
{
    NSWindow *window = [self window];
    if (!window) {
        return;
    }
    /* Wizard Desktop: no aspect lock; any shape the user drags is fine. */
    [window setContentResizeIncrements:NSMakeSize(1.0, 1.0)];
    if ([window styleMask] & NSWindowStyleMaskFullScreen) {
        [window setContentSize:[self screenSafeAreaSize]];
        [window center];
    }
}

- (void) updateScale
'''
sub(r'- \(void\) resizeWindow\n\{.*?\n\}\n\n- \(void\) updateScale\n', lambda m: RESIZE, 1, flags=re.S)

# 7. the window is resizable from birth (not only after zoom-to-fit is applied)
sub(r'styleMask:NSWindowStyleMaskTitled\|NSWindowStyleMaskMiniaturizable\|NSWindowStyleMaskClosable\n',
    'styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskClosable|NSWindowStyleMaskResizable\n',
    1)

# 8. open at a normal desktop-app size: 1280x840 points, capped to the screen
INITIAL = r'''static NSRect cocoa_initial_window_frame(void)
{
    NSScreen *hostScreen = [NSScreen mainScreen];
    if (!hostScreen) {
        return NSMakeRect(0.0, 0.0, 1280.0, 840.0);
    }

    NSRect available = [hostScreen visibleFrame];
    NSSize size = NSMakeSize(floor(MIN(1280.0, NSWidth(available) * 0.85)),
                             floor(MIN(840.0, NSHeight(available) * 0.85)));
    size.width = MAX(size.width, 520.0);
    size.height = MAX(size.height, 480.0);

    return NSMakeRect(floor(NSMidX(available) - size.width / 2.0),
                      floor(NSMidY(available) - size.height / 2.0),
                      size.width, size.height);
}
'''
sub(r'static NSRect cocoa_initial_window_frame\(void\)\n\{.*?\n\}\n', lambda m: INITIAL, 1, flags=re.S)

# 5. product name
n_before = s.count("Try Omarchy")
if n_before == 0:
    sys.exit("wizard-cocoa-edit: no product strings found")
s = s.replace("Try Omarchy", "Wizard")

open(path, "w", encoding="utf-8").write(s)
print(f"wizard-cocoa-edit: OK (host chords, Ctrl-Cmd-F, window memory, {n_before} product strings)")
