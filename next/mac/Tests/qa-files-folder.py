#!/usr/bin/env python3
"""Native source/core sharing regression (no GUI or owner preferences).

The old first-run folder/default-Documents harness is superseded by
ONBOARDING-PRIVACY.md. Never pre-answer folder consent to prove fresh onboarding.
Real installed-app GUI/TCC/VM acceptance requires a separately admitted session.
"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(root / 'test_onboarding_privacy.py')], check=True)
subprocess.run([sys.executable, str(root / 'run_onboarding_privacy_checks.py')], check=True)
