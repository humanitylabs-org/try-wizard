#!/usr/bin/env python3
"""wizard-os#133: a new Linux box starts with the browser boundary on, but the Mac guest's setup page calls the owner
API on loopback without the shell token yet, so the guest build installs with WIZARD_BROWSER_BOUNDARY=0."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "overlay/opt/wizard/bin/wizard-provision").read_text()


def main() -> None:
    runs = [l for l in SRC.splitlines() if ("bash /tmp/os.sh" in l or "wizard-app-manager/install.sh" in l)
            and not l.lstrip().startswith("#")]
    assert len(runs) == 2, runs
    for line in runs:
        assert "WIZARD_BROWSER_BOUNDARY=0" in line, line
    print("ok: the Mac guest installs with the browser boundary off")


if __name__ == "__main__":
    main()
