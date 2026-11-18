import Foundation

// try-wizard#109 fixture. test_legacy_documents_share.py compiles the real Shared sources with this file and
// pastes the Host's unchanged boot-time files-share block in place of the HOST_FILES_SHARE line below.
// Virtualization is replaced by spies so every folder the Host would share is recorded.

var sharedDirectoryURLs: [URL] = []
final class VZSharedDirectory { init(url: URL, readOnly: Bool) { sharedDirectoryURLs.append(url) } }
final class VZSingleDirectoryShare { init(directory: VZSharedDirectory) {} }
final class VZVirtioFileSystemDeviceConfiguration {
    let tag: String
    var share: VZSingleDirectoryShare?
    init(tag: String) { self.tag = tag }
}
final class FakeVMConfiguration { var directorySharingDevices: [VZVirtioFileSystemDeviceConfiguration] = [] }
var logLines: [String] = []
func log(_ message: String) { logLines.append(message) }

/// One Host VM boot's files-share decision. Returns the folders handed to VZSharedDirectory.
func hostBoot() -> [String] {
    sharedDirectoryURLs = []
    let c = FakeVMConfiguration()
    // HOST_FILES_SHARE
    _ = c
    return sharedDirectoryURLs.map { $0.path }
}

var failures: [String] = []
func check(_ ok: Bool, _ what: String) {
    print((ok ? "ok   " : "FAIL ") + what)
    if !ok { failures.append(what) }
}
let fm = FileManager.default
func exists(_ path: String) -> Bool { fm.fileExists(atPath: path) }

/// Exactly what builds before #109 wrote: {"path": ...}, pretty-printed, no explicit marker.
func writeAsOldBuild(_ path: String) throws {
    try fm.createDirectory(at: WizardShared.supportDir, withIntermediateDirectories: true)
    let d = try JSONSerialization.data(withJSONObject: ["path": path], options: [.prettyPrinted])
    try d.write(to: WizardShared.filesFolderFile, options: .atomic)
}

func run(root: URL) throws {
    let home = root.appendingPathComponent("home", isDirectory: true)
    try fm.createDirectory(at: home, withIntermediateDirectories: true)
    let documents = home.appendingPathComponent("Documents").path
    let legacy = home.appendingPathComponent("Documents/Wizard MVP").path

    // 1. Upgrade over an old build's automatic Documents share.
    try writeAsOldBuild(legacy)
    let before = try Data(contentsOf: WizardShared.filesFolderFile)
    let mounts = hostBoot()
    check(mounts.isEmpty, "1 legacy auto share: Host boot shares no folder (got \(mounts))")
    check(!exists(legacy) && !exists(documents), "1 legacy auto share: Documents/Wizard MVP was not created")
    check(WizardShared.activeSharedFolder == nil, "1 legacy auto share: activeSharedFolder is nil")
    check(WizardShared.filesFolder?.path == legacy, "1 legacy auto share: raw saved path kept for display")
    check((try? Data(contentsOf: WizardShared.filesFolderFile)) == before, "1 legacy auto share: files-folder.json not rewritten")

    // 3. Legacy spellings: trailing slash, extra separators and dots, letter case, symlinked home.
    let link = root.appendingPathComponent("home-link")
    try fm.createSymbolicLink(at: link, withDestinationURL: home)
    for variant in [legacy + "/", home.path + "//Documents/./Wizard MVP//", home.path + "/documents/WIZARD MVP",
                    link.path + "/Documents/Wizard MVP/"] {
        try writeAsOldBuild(variant)
        let m = hostBoot()
        check(m.isEmpty, "3 legacy variant \(variant): no share (got \(m))")
        check(!exists(documents), "3 legacy variant \(variant): Documents untouched")
    }

    // An unmarked share anywhere else (e.g. ~/Wizard chosen in an earlier build) is still honoured.
    let other = home.appendingPathComponent("Wizard").path
    try writeAsOldBuild(other)
    check(hostBoot() == [other], "4 unmarked non-legacy share is still mounted")

    // 2. The owner's own sharing action writes the marker and is mounted on relaunch, even for the legacy path.
    let chosen = home.appendingPathComponent("Chosen Folder", isDirectory: true)
    try WizardShared.setFilesFolder(chosen)
    let saved = (try? JSONSerialization.jsonObject(with: Data(contentsOf: WizardShared.filesFolderFile))) as? [String: Any]
    check(saved?["explicit"] as? Bool == true, "2 explicit choice is saved with \"explicit\": true")
    check(hostBoot() == [chosen.path], "2 explicit choice is mounted on relaunch")
    try WizardShared.setFilesFolder(URL(fileURLWithPath: legacy, isDirectory: true))
    check(hostBoot() == [legacy], "2 explicitly choosing Documents/Wizard MVP again is honoured")
}

let fixtureRoot = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let defaults = UserDefaults(suiteName: WizardShared.appBundleID)!
let previous = defaults.string(forKey: "DataHome")
defaults.set(fixtureRoot.appendingPathComponent("data").path, forKey: "DataHome")
do { try run(root: fixtureRoot) } catch { failures.append("error: \(error)") }
if let previous { defaults.set(previous, forKey: "DataHome") } else { defaults.removeObject(forKey: "DataHome") }
print(failures.isEmpty ? "LEGACY_DOCUMENTS_SHARE_PASS" : "LEGACY_DOCUMENTS_SHARE_FAIL \(failures.count)")
exit(failures.isEmpty ? 0 : 1)
