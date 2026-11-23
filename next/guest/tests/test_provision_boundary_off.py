#!/usr/bin/env python3
"""wizard-os#133 on the Mac guest.

1. The setup page sends the box's shell token on its owner calls when the box has one, so it keeps working on a guest
   where the browser boundary is on (`wam browser-boundary on`), and sends nothing when there is no token.
2. A new Linux box starts with the browser boundary on (wizard-app-manager#957). The Mac app's own calls into the guest
   (the update lease on /wizard/v1/maintenance) don't carry the token yet, so the guest build installs with
   WIZARD_BROWSER_BOUNDARY=0 until they do. `wam browser-boundary on` in the guest still turns it on.
"""
import asyncio
import importlib.util
import tempfile
from pathlib import Path

GUEST = Path(__file__).resolve().parents[1]
SRC = (GUEST / "overlay/opt/wizard/bin/wizard-provision").read_text()


def load_server():
    spec = importlib.util.spec_from_file_location("wizard_setup_server_boundary_test",
                                                  GUEST / "overlay/opt/wizard/setup/server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sent_headers(server, token_text):
    with tempfile.TemporaryDirectory() as d:
        server.SHELL_TOKEN_FILE = Path(d) / "browser-boundary" / "shell-token"
        if token_text is not None:
            server.SHELL_TOKEN_FILE.parent.mkdir()
            server.SHELL_TOKEN_FILE.write_text(token_text)
        seen = {}

        async def fake_request(method, url, body, headers, timeout):
            seen.update(url=url, headers=dict(headers))
            return 200, {}

        server._request = fake_request
        asyncio.run(server.shell("GET", server.PRIVATE_FIRST_STATE, headers={"Origin": "http://x"}))
        return seen


def test_setup_sends_the_shell_token():
    server = load_server()
    token = "ab" * 32
    got = sent_headers(server, token + "\n")
    assert got["headers"].get("X-Wizard-Shell-Token") == token, got
    assert got["headers"]["Origin"] == "http://x" and got["url"].startswith(server.SHELL_ORIGIN), got
    assert "X-Wizard-Shell-Token" not in sent_headers(server, None)["headers"]          # no token file: no header
    assert "X-Wizard-Shell-Token" not in sent_headers(server, "not-a-token")["headers"]  # junk is never sent


def test_guest_build_installs_with_the_boundary_off():
    runs = [l for l in SRC.splitlines() if ("bash /tmp/os.sh" in l or "wizard-app-manager/install.sh" in l)
            and not l.lstrip().startswith("#")]
    assert len(runs) == 2, runs
    for line in runs:
        assert "WIZARD_BROWSER_BOUNDARY=0" in line, line


def main() -> None:
    test_setup_sends_the_shell_token()
    test_guest_build_installs_with_the_boundary_off()
    print("ok: the setup page sends the shell token; the Mac guest build installs with the boundary off")


if __name__ == "__main__":
    main()
