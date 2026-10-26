#!/usr/bin/env python3
"""Mac-executed fixtures extracted from production, plus portable source contracts.
Run with --native on Thales; no preferences, VM or owner state is opened.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'next/mac/App/main.swift'
SHARED = ROOT / 'next/mac/Shared/Shared.swift'
NATIVE = False


def member(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def native_source():
    app, shared = APP.read_text(), SHARED.read_text()
    functions = [member(app, '    static func error('),
                 member(app, '    static func sha256('),
                 member(app, '    static func verifyManifest(')]
    classifier = member(shared, '    static var legacyBootstrapNeeded:')
    feed = member(app, '    static var osFeedURL:')
    return '''import Foundation
import CryptoKit
import Darwin
enum Validator {
''' + '\n'.join(functions) + '''
}
enum Store {
    static let d = UserDefaults(suiteName: "fixture." + UUID().uuidString)!
    static let downloadsBase = "https://downloads.aiwizards.com/"
''' + feed + '''
}
enum WizardUpdate {
    static func error(_ text: String) -> NSError { Validator.error(text) }
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var journal: URL { dir.appendingPathComponent("transaction.json") }
    static func json(_ url: URL) -> [String:Any] {
        guard let d = try? Data(contentsOf:url), let o = try? JSONSerialization.jsonObject(with:d) as? [String:Any] else { return [:] }
        return o
    }
}
enum WizardShared {
    static let supportDir = URL(fileURLWithPath:CommandLine.arguments[1])
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var osInstalled: Bool { true }
''' + classifier + '''
}
''' + (ROOT/'next/mac/Shared/DiskIdentity.swift').read_text().replace('import Foundation', '') + '''
let dir = WizardShared.osDir
try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true)
let file = dir.appendingPathComponent("payload")
try Data("fixture bytes".utf8).write(to:file)
func manifest(_ version:String, _ files:[String:String]) throws {
    try JSONSerialization.data(withJSONObject:["version":version,"files":files]).write(to:dir.appendingPathComponent("manifest.json"))
}
func expectRejected(_ label:String) {
    do { try Validator.verifyManifest(in:dir); fatalError("accepted " + label) } catch { print("PASS rejects " + label) }
}
let digest = try Validator.sha256(of:file)
for version in ["0.3.0","0.4.0","0.4.1","0.5.0"] {
    try manifest(version,["payload":digest]); try Validator.verifyManifest(in:dir)
    print("PASS accepts " + version)
    assert(WizardShared.legacyBootstrapNeeded == (version == "0.3.0"))
    print("PASS bootstrap classification " + version)
}
try manifest("9.9.9",["payload":digest]);expectRejected("unknown version")
assert(WizardShared.legacyBootstrapNeeded)
print("PASS unknown version not precomposed")
for version in ["0.4.1","0.5.0"] {
    try manifest(version,["payload":String(repeating:"0",count:64)]);expectRejected("corrupt digest " + version)
    try manifest(version,["../payload":digest]);expectRejected("path traversal " + version)
    try manifest(version,[:]);expectRejected("empty file list " + version)
    try manifest(version,["missing":digest]);expectRejected("missing file " + version)
}
assert(Store.osFeedURL.absoluteString == "https://downloads.aiwizards.com/os/p2/latest.json")
print("PASS default feed p2")
'''


class FactoryAdmissionTests(unittest.TestCase):
    def test_accepts_0_5_0_in_validator_and_bootstrap_classifier(self):
        self.assertIn('"0.5.0"', member(APP.read_text(), '    static func verifyManifest('))
        self.assertIn('"0.5.0"', member(SHARED.read_text(), '    static var legacyBootstrapNeeded:'))

    def test_still_accepts_0_4_1_and_existing_versions(self):
        validator = member(APP.read_text(), '    static func verifyManifest(')
        classifier = member(SHARED.read_text(), '    static var legacyBootstrapNeeded:')
        for version in ('0.3.0', '0.4.0', '0.4.1'):
            self.assertIn('"'+version+'"', validator)
        for version in ('0.4.0', '0.4.1'):
            self.assertIn('"'+version+'"', classifier)

    def test_rejects_unknown_versions_and_corrupt_hashes(self):
        validator = member(APP.read_text(), '    static func verifyManifest(')
        self.assertIn('.contains(imageVersion)', validator)
        self.assertIn('guard got == want.lowercased() else { throw bad }', validator)
        self.assertIn('!rel.contains("..")', validator)

    def test_default_feed_is_p2(self):
        feed = member(APP.read_text(), '    static var osFeedURL:')
        self.assertIn('?? Store.downloadsBase + "os/p2/latest.json"', feed)

    def test_native_accepts_0_5_0_still_accepts_0_4_1_rejects_unknown_default_feed_p2(self):
        if not NATIVE:
            self.skipTest('run --native on Thales for production Swift execution')
        with tempfile.TemporaryDirectory(prefix='factory-admission.') as tmp:
            path = Path(tmp)
            (path/'main.swift').write_text(native_source())
            subprocess.run(['xcrun','swiftc','-swift-version','5',path/'main.swift','-o',path/'fixture'],check=True,timeout=120)
            subprocess.run([path/'fixture',path/'data'],check=True,timeout=30)
        print(json.dumps({'productionSources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (APP, SHARED)}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--native',action='store_true'); args, rest = parser.parse_known_args()
    NATIVE = args.native
    unittest.main(argv=[__file__,*rest],verbosity=2)
