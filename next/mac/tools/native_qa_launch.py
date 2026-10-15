"""Launch installed native QA through the logged-in user's LaunchServices.

A direct Popen of Contents/MacOS/Wizard is NOT a Finder launch: it retains
SSH/background responsibility for privacy requests, whereas its NSWorkspace
Host and Sparkle relaunch do not. Never use an all-internal DataHome to conceal
that difference. This helper does not grant consent or reset TCC.
"""
import os
import pathlib
import plistlib
import subprocess

APP_ID = 'org.humanitylabs.wizard.mvp'


def launch_command(app, uid):
    app = pathlib.Path(app)
    if not app.is_absolute() or app.suffix != '.app':
        raise ValueError('An absolute installed .app path is required')
    if app.parent not in (pathlib.Path('/Applications'), pathlib.Path.home() / 'Applications'):
        raise ValueError('Install the tool in Applications; keep QA work data on the external volume')
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        raise ValueError('A logged-in non-root GUI user is required')
    # SSH may have the right UID but the wrong audit session. asuser requires
    # root to switch that session; immediately drop back to the console UID for
    # open(1), so neither the app nor its preferences are root-owned.
    return ['/usr/bin/sudo', '-n', '/bin/launchctl', 'asuser', str(uid),
            '/usr/bin/sudo', '-n', '-u', '#' + str(uid),
            '/usr/bin/open', '-g', '-j', str(app)]


def launch_installed(app):
    """Background-first launch; callers must verify the exact PID and Host status.

    An open(1) success is only launch admission, not application/VM readiness.
    Refuse another GUI owner rather than changing ownership or stealing focus.
    """
    app = pathlib.Path(app)
    uid = os.getuid()
    command = launch_command(app, uid)
    if os.stat('/dev/console').st_uid != uid:
        raise RuntimeError('No GUI console session owned by this QA user')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != APP_ID:
        raise ValueError('Refuse a non-MVP bundle')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, timeout=30)
    subprocess.run(command, check=True, timeout=30)
