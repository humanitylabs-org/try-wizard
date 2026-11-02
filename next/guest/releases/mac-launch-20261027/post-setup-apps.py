#!/usr/bin/env python3
"""Boot-resumable trigger for WAM's existing default-app installer, never an installer itself.
Only factory images with this root-owned release opt in; existing guests are untouched.
"""
import fcntl
import json
import os
import subprocess
from pathlib import Path

STATE = Path('/var/lib/wizard/setup.json')
RELEASE = Path('/var/lib/wizard/default-apps-release.json')
HOME = Path('/home/wizard/.wizard-os')
WAM = Path('/home/wizard/.local/bin/wam')


def run(state=STATE, release=RELEASE, home=HOME, runner=subprocess.run):
    # No pull, app install, marker or wait on any onboarding HTTP request.
    if not release.is_file() or not state.is_file():
        return False
    try:
        setup = json.loads(state.read_text())
        if not isinstance(setup, dict) or setup.get('done') is not True:
            return False
    except (OSError, ValueError):
        return False
    done = home / 'factory-default-apps.done'
    if done.exists():
        return True
    home.mkdir(parents=True, exist_ok=True)
    with (home / 'factory-default-apps.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        if done.exists():
            return True
        env = {k: v for k, v in os.environ.items() if k not in
               ('WAM_REF', 'WIZARD_RELEASE_PINS', 'WIZARD_MODE', 'WIZARD_SHELL_IMAGE',
                'WIZARD_UX_IMAGE', 'WIZARD_AGENT_SERVICE_IMAGE')}
        env.update(HOME='/home/wizard', WIZARD_RELEASE_PINS=str(release), WIZARD_MODE='fresh')
        # Restore the full default policy to the SAME canonical WAM release file.
        # Future normal Store/agent/API calls see the default apps too, not a second catalogue.
        canonical = home / 'release-pins.json'
        pending = canonical.with_suffix('.new')
        pending.write_bytes(release.read_bytes())
        pending.replace(canonical)
        result = runner([str(WAM), 'bootstrap'], env=env, capture_output=True, text=True,
                        timeout=3600, check=True)
        # WAM CLI exits zero even when bootstrap reports per-app failures. Never mark
        # those complete: the timer retries, WAM leaves installed apps/alternatives alone.
        decoder = json.JSONDecoder()
        outcome = None
        for offset, char in enumerate(result.stdout):
            if char != '{':
                continue
            try:
                value, end = decoder.raw_decode(result.stdout, offset)
            except ValueError:
                continue
            if not result.stdout[end:].strip() and isinstance(value, dict) and 'failed' in value:
                outcome = value
                break
        if outcome is None:
            return False
        if not isinstance(outcome.get('failed'), dict) or outcome['failed']:
            return False
        tmp = done.with_suffix('.new')
        tmp.write_text(json.dumps({'release': json.loads(release.read_text())['version']}) + '\n')
        tmp.replace(done)
        return True


if __name__ == '__main__':
    run()
