#!/usr/bin/env python3
"""Thales-only focused Swift presentation check (run under the parent's worker.lock).
Does not build the app or alter shared source. Native UI/VM checks remain separate.
"""
import os
from pathlib import Path
import platform
import subprocess
import tempfile


def main():
    if platform.system() != "Darwin":
        raise SystemExit("Run only on Thales/macOS under worker.lock; no VPS Swift compilation.")
    source = (Path(__file__).resolve().parents[1] / "mac/App/main.swift").read_text()
    model = source.split("struct LocalVoiceStatus: Decodable {", 1)[1].split("// MARK: - Window", 1)[0]
    checks = r'''
func check(_ json: String) throws -> LocalVoiceStatus {
    try JSONDecoder().decode(LocalVoiceStatus.self, from: Data(json.utf8))
}
let preparing = try check(#"{"state":"preparing","stage":"Loading voice model","downloaded":100,"total":100}"#)
precondition(!preparing.isReady && preparing.canRetry)
precondition(preparing.summary.contains("Preparing local voice") && preparing.summary.contains("Loading voice model"))
precondition(preparing.summary.contains("Model:") && !preparing.summary.contains("ready"))
let ready = try check(#"{"state":"ready","stage":"Local voice ready","downloaded":100,"total":100}"#)
precondition(ready.isReady && !ready.canRetry && ready.summary.contains("Local voice ready"))
let retrying = try check(#"{"state":"retrying","stage":"Local voice will retry","downloaded":50,"total":100}"#)
precondition(!retrying.isReady && retrying.canRetry && retrying.summary.contains("retrying"))
let failed = try check(#"{"state":"error","stage":"Local voice status unavailable","downloaded":0,"total":0}"#)
precondition(!failed.isReady && failed.canRetry && !failed.summary.contains("Model:"))
let unknown = try check(#"{"state":"bogus","stage":"","downloaded":0,"total":0}"#)
precondition(!unknown.isReady && unknown.summary == "Local voice needs attention")
print("PASS: LocalVoiceStatus preparing/full-bytes-not-ready/ready/retrying/error/unknown")
'''
    with tempfile.TemporaryDirectory(prefix="wizard-voice-swift-", dir=os.environ.get("TMPDIR")) as tmp:
        script = Path(tmp) / "main.swift"
        script.write_text("import Foundation\nstruct LocalVoiceStatus: Decodable {" + model + checks)
        subprocess.run(["swift", str(script)], check=True, timeout=90)


if __name__ == "__main__":
    main()
