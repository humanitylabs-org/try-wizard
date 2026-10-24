#!/usr/bin/env python3
"""Run exact production manifest validator + classifier bodies in a bounded Mac fixture.
Only absent disk-completion receipt plumbing is stubbed; this is not a fresh-install proof.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def block(source, marker):
    start = source.index(marker)
    left = source.index('{', start)
    depth = 1
    for end in range(left + 1, len(source)):
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
            if not depth:
                return source[start:end + 1]
    raise ValueError('unterminated production block')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--work', type=Path, required=True)
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    app = (a.source / 'App/main.swift').read_text()
    shared = (a.source / 'Shared/Shared.swift').read_text()
    validator = block(app, 'static func verifyManifest(in dir: URL) throws')
    hasher = block(app, 'static func sha256(of url: URL) throws')
    classifier = block(shared, 'static var legacyBootstrapNeeded: Bool')
    swift = '''import Foundation
import CryptoKit
let fixture = URL(fileURLWithPath: CommandLine.arguments[1])
struct WizardUpdate {
    static var dir: URL { fixture }; static var journal: URL { fixture.appendingPathComponent("missing.json") }
    static func json(_ path: URL) -> [String:Any] {
        guard let d = try? Data(contentsOf: path), let j = try? JSONSerialization.jsonObject(with:d) as? [String:Any] else { return [:] }; return j
    }
}
struct WizardDiskIdentity {
    static func completed(_ a: [String:Any], modern: [String:Any], journal: [String:Any], disk: URL, home: URL) -> Bool { false }
}
struct WizardShared {
    static var osInstalled: Bool { true }; static var osDir: URL { fixture }; static var supportDir: URL { fixture }
''' + classifier + '''
}
struct Installer {
    static func error(_ s: String) -> NSError { NSError(domain:"fixture", code:1, userInfo:[NSLocalizedDescriptionKey:s]) }
''' + hasher + '\n' + validator + '''
}
try FileManager.default.createDirectory(at:fixture, withIntermediateDirectories:true)
let payload = fixture.appendingPathComponent("rootfs.img")
try Data("fixture disk bytes".utf8).write(to:payload)
let good = try Installer.sha256(of:payload)
var checks = 0
for (version, allowed, legacy) in [("0.5.0",true,false),("0.4.0",true,false),("0.3.0",true,true),("0.6.0",false,true)] {
    let m:[String:Any] = ["version":version,"files":["rootfs.img":good]]
    try JSONSerialization.data(withJSONObject:m).write(to:fixture.appendingPathComponent("manifest.json"))
    var ok = true; do { try Installer.verifyManifest(in:fixture) } catch { ok = false }
    precondition(ok == allowed, "validator " + version)
    precondition(WizardShared.legacyBootstrapNeeded == legacy, "classifier " + version)
    checks += 2
}
try JSONSerialization.data(withJSONObject:["version":"0.5.0","files":["rootfs.img":String(repeating:"0",count:64)]]).write(to:fixture.appendingPathComponent("manifest.json"))
var refused = false; do { try Installer.verifyManifest(in:fixture) } catch { refused = true }
precondition(refused,"corrupt payload must fail"); checks += 1
print("production manifest/classifier checks passed: \\(checks)")
'''
    driver = a.work / 'factory-admission.swift'
    driver.write_text(swift)
    subprocess.run(['/usr/bin/swift', str(driver), str(a.work / 'fixture')], check=True, timeout=120)


if __name__ == '__main__':
    main()
