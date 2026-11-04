import Foundation

@main struct RemovalTests {
    static let fm = FileManager.default
    static var passed = 0
    static func require(_ ok: @autoclosure () throws -> Bool, _ message: String) throws {
        if try ok() == false { throw WizardRemovalPlan.error("FAIL: \(message)") }
    }
    static func rejects(_ label: String, _ block: () throws -> Void) throws {
        do { try block() } catch { print("PASS \(label)"); passed += 1; return }
        throw WizardRemovalPlan.error("FAIL: \(label) did not refuse")
    }
    static func main() throws {
        guard CommandLine.arguments.count == 2 else { fatalError("Pass a NEW disposable fixture root") }
        let root = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL.resolvingSymlinksInPath()
        guard root.lastPathComponent.hasPrefix("wizard-removal-fixture-"), !fm.fileExists(atPath: root.path) else {
            fatalError("Refusing existing or unlabelled fixture root")
        }
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        var events: [String] = []
        func write(_ url: URL, _ text: String = "marker") throws {
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(text.utf8).write(to: url)
        }
        func plan(_ name: String, _ action: WizardRemovalPlan.Action, filesOverride: URL? = nil, dataOverride: URL? = nil) throws -> WizardRemovalPlan {
            let base = root.appendingPathComponent(name), home = base.appendingPathComponent("owner")
            let data = dataOverride ?? home.appendingPathComponent("Library/Application Support/Wizard")
            let app = base.appendingPathComponent("Applications/Wizard.app")
            let files = filesOverride ?? home.appendingPathComponent("Documents/Wizard Files")
            let p = WizardRemovalPlan(action: action, home: home, library: home.appendingPathComponent("Library"), dataHome: data, app: app,
                                      files: [files], bundleIDs: ["test.wizard.removal", "test.wizard.removal.host"])
            try write(data.appendingPathComponent("os/disk.img"), "same-state-marker")
            try write(data.appendingPathComponent("os/manifest.json"), "manifest-marker")
            try write(app.appendingPathComponent("Contents/Info.plist"))
            try write(files.appendingPathComponent("owner-file.txt"), "never-change")
            for e in p.entries.dropFirst() { try write(e.url.appendingPathComponent("fixture-marker")) }
            return p
        }
        let effects = WizardRemovalEffects(remove: { url in
            try require(WizardRemovalPlan.contains(root, url), "effect escaped fixture")
            events.append("remove:" + url.path)
            if fm.fileExists(atPath: url.path) { try fm.removeItem(at: url) }
        }, clearPreferences: { events.append("prefs:" + $0) }, resetPrivacy: { events.append("privacy:" + $0) }, trash: { url in
            try require(WizardRemovalPlan.contains(root, url), "trash escaped fixture")
            events.append("trash:" + url.path)
            if fm.fileExists(atPath: url.path) { try fm.moveItem(at: url, to: url.appendingPathExtension("fixture-trash")) }
        }, clone: { source, target in
            events.append("clone")
            // Contract fixture only. Actual clonefile/restore is a separate native acceptance gate.
            try fm.copyItem(at: source, to: target)
        })
        func record(_ label: String) { print("PASS \(label)"); passed += 1 }
        func snapshot(_ label: String, _ p: WizardRemovalPlan) throws {
            let paths = p.inventory.map(\.url) + [p.app, p.files[0], p.dataHome.appendingPathComponent("os/disk.img")]
            let rows = paths.map { ["path": $0.path, "exists": fm.fileExists(atPath: $0.path)] as [String: Any] }
            try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys]).write(to: root.appendingPathComponent(label + ".json"))
        }
        for action in [WizardRemovalPlan.Action.keepData, .deleteData, .startFresh] {
            let p = try plan(action.rawValue, action)
            try p.validate(); try snapshot(action.rawValue + "-before", p)
            events = []
            try WizardRemoval.execute(p, isStopped: { true }, effects: effects)
            try snapshot(action.rawValue + "-after", p)
            try require(fm.fileExists(atPath: p.app.path) == (action == .startFresh), "app keep/trash")
            try require(fm.fileExists(atPath: p.dataHome.path) == (action == .keepData), "data keep/delete")
            try require(try String(contentsOf: p.files[0].appendingPathComponent("owner-file.txt"), encoding: .utf8) == "never-change", "Files content changed")
            if action == .keepData {
                try require(events.count == 1 && events[0].hasPrefix("trash:"), "Keep must remove app ONLY")
                try fm.moveItem(at: p.app.appendingPathExtension("fixture-trash"), to: p.app)
                try require(try String(contentsOf: p.dataHome.appendingPathComponent("os/disk.img"), encoding: .utf8) == "same-state-marker", "reinstall marker")
                record("Keep reinstalls with the same fixture marker (not guest-boot proof)")
            } else {
                try require(p.entries.count == 15, "inventory includes DataHome and seven paths per domain")
                for e in p.entries { try require(!fm.fileExists(atPath: e.url.path), "entry remained: \(e.url.path)") }
                try require(events.filter { $0.hasPrefix("prefs:") }.count == 2, "both prefs domains")
                try require(events.filter { $0.hasPrefix("privacy:") }.count == 2, "both privacy domains")
            }
            try WizardRemoval.execute(p, isStopped: { true }, effects: effects)
            record("\(action.rawValue) inventory, Files preservation, idempotent retry")
        }
        let late = try plan("late-storage", .deleteData)
        try WizardRemoval.execute(late, isStopped: { true }, effects: effects)
        // Model WebKit recreating every scoped residue path after the first deletion.
        for entry in late.inventory.dropFirst() { try write(entry.url.appendingPathComponent("late-marker")) }
        // A separately created DataHome must NEVER be removed by the late storage pass.
        try write(late.dataHome.appendingPathComponent("new-install"), "retain-new-data")
        let unrelated = late.library.appendingPathComponent("WebKit/test.wizard.removal.other/marker")
        try write(unrelated, "retain-unrelated")
        events = []
        try WizardRemoval.finishStorageCleanup(late, isStopped: { true }, effects: effects)
        for entry in late.inventory.dropFirst() { try require(!fm.fileExists(atPath: entry.url.path), "late residue remained") }
        try require(fm.fileExists(atPath: unrelated.path) && fm.fileExists(atPath: late.dataHome.appendingPathComponent("new-install").path), "late cleanup escaped its storage scope")
        try require(try String(contentsOf: late.files[0].appendingPathComponent("owner-file.txt"), encoding: .utf8) == "never-change", "late sweep changed Files")
        try require(!events.contains(where: { $0.hasPrefix("privacy:") || $0.hasPrefix("trash:") }), "late sweep repeated privacy/trash effects")
        record("late WebKit/cache/cookie/state cleanup preserves Files, unrelated domain and new DataHome")
        events = []
        try rejects("late sweep refuses restarted Host") { try WizardRemoval.finishStorageCleanup(late, isStopped: { false }, effects: effects) }
        try require(events.isEmpty, "late stopped fence allowed effects")
        let keep = try plan("late-keep", .keepData); events = []
        try WizardRemoval.finishStorageCleanup(keep, isStopped: { true }, effects: effects)
        try require(events.isEmpty, "Keep late sweep changed settings"); record("Keep late cleanup is inert")

        // Pure injected preferences only: never call the real user's CFPreferences/TCC here.
        var prefKeys: [WizardRemovalPreferenceHost: [String]] = [.any: ["DataHome", "Bookmarks"], .current: ["ByHostWindow"]]
        var flushed: [WizardRemovalPreferenceHost] = []; var processClears = 0
        try WizardRemovalPreferences.clear("test.wizard.removal", processDomain: { processClears += 1 }, synchronize: { flushed.append($0); return true }, keys: { prefKeys[$0] ?? [] }, remove: { prefKeys[$0] = []; _ = $1 })
        try require(processClears == 1 && prefKeys.values.allSatisfy(\.isEmpty) && flushed.count == 4, "both host scopes must flush and read back")
        record("no-reboot preferences clear process, any-host and current-host scopes with readback")
        try rejects("preferences reject failed synchronization") {
            try WizardRemovalPreferences.clear("test.wizard.removal", processDomain: {}, synchronize: { _ in false }, keys: { _ in [] }, remove: { _, _ in })
        }
        try rejects("preferences reject stale readback") {
            try WizardRemovalPreferences.clear("test.wizard.removal", processDomain: {}, synchronize: { _ in true }, keys: { _ in ["stale"] }, remove: { _, _ in })
        }
        let external = try plan("external", .deleteData, dataOverride: root.appendingPathComponent("external-volume/WizardData"))
        try WizardRemoval.execute(external, isStopped: { true }, effects: effects)
        try require(!fm.fileExists(atPath: external.dataHome.path), "external DataHome left behind"); record("external DataHome")
        let running = try plan("running", .deleteData); events = []
        try rejects("running VM refuses before ALL effects") { try WizardRemoval.execute(running, isStopped: { false }, effects: effects) }
        try require(events.isEmpty && fm.fileExists(atPath: running.dataHome.path), "running refusal touched disk")
        events = []; var checks = 0
        try rejects("VM restart between effects refuses remaining work") {
            try WizardRemoval.execute(running, isStopped: { checks += 1; return checks == 1 }, effects: effects)
        }
        try require(events.isEmpty, "restart refusal did effects")
        let inside = root.appendingPathComponent("inside/owner/Library/Application Support/Wizard/Files")
        let overlap = try plan("inside", .deleteData, filesOverride: inside)
        try rejects("Files inside DataHome") { try overlap.validate() }
        let equal = try plan("equal", .deleteData, filesOverride: root.appendingPathComponent("equal/owner/Library/Application Support/Wizard"))
        try rejects("Files equal DataHome") { try equal.validate() }
        let parent = try plan("parent", .deleteData, filesOverride: root.appendingPathComponent("parent/owner"))
        try rejects("Files around DataHome") { try parent.validate() }
        let linked = root.appendingPathComponent("linked-files")
        try fm.createSymbolicLink(at: linked, withDestinationURL: overlap.dataHome)
        let alias = WizardRemovalPlan(action: .deleteData, home: overlap.home, library: overlap.library, dataHome: overlap.dataHome, app: overlap.app, files: [linked], bundleIDs: overlap.bundleIDs)
        try rejects("symlink Files overlap") { try alias.validate() }
        let appFiles = try plan("app-files", .deleteData, filesOverride: root.appendingPathComponent("app-files/Applications/Wizard.app/Files"))
        try rejects("Files in app bundle") { try appFiles.validate() }
        let unsafe = WizardRemovalPlan(action: .deleteData, home: running.home, library: running.library, dataHome: running.home, app: running.app, files: [root.appendingPathComponent("safe-files")], bundleIDs: running.bundleIDs)
        try rejects("home as DataHome") { try unsafe.validate() }
        let redirected = root.appendingPathComponent("redirected-data")
        try fm.createSymbolicLink(at: redirected, withDestinationURL: running.dataHome)
        let redirectedPlan = WizardRemovalPlan(action: .deleteData, home: running.home, library: running.library, dataHome: redirected, app: running.app, files: running.files, bundleIDs: running.bundleIDs)
        try rejects("redirected DataHome refuses") { try redirectedPlan.validate() }
        let fresh = try plan("clone", .startFresh), backup = root.appendingPathComponent("stopped-backup")
        try WizardRemoval.execute(fresh, isStopped: { true }, backup: backup, effects: effects)
        try fm.createDirectory(at: fresh.dataHome, withIntermediateDirectories: true)
        try fm.copyItem(at: backup, to: fresh.dataHome.appendingPathComponent("os"))
        try require(try String(contentsOf: fresh.dataHome.appendingPathComponent("os/disk.img"), encoding: .utf8) == "same-state-marker", "backup restore marker")
        record("backup/restore fixture contract (copy fixture, not APFS clone)")
        let failedBackup = try plan("failed-backup", .startFresh)
        var badEffects = effects; badEffects.clone = { _, _ in throw WizardRemovalPlan.error("clone failure") }; events = []
        try rejects("clone failure leaves all data") { try WizardRemoval.execute(failedBackup, isStopped: { true }, backup: root.appendingPathComponent("clone-fails"), effects: badEffects) }
        try require(events.isEmpty && fm.fileExists(atPath: failedBackup.dataHome.path), "clone failure touched state")
        try rejects("backup cannot land in Files") { try WizardRemoval.execute(failedBackup, isStopped: { true }, backup: failedBackup.files[0].appendingPathComponent("backup"), effects: effects) }
        let watch = WizardMissingAppWatch(originalApp: running.app)
        try require(!watch.isMissing(), "watch says existing app missing")
        try fm.moveItem(at: running.app, to: running.app.appendingPathExtension("moved"))
        try require(watch.isMissing(), "watch followed moved bundle")
        record("original app path disappearance (not a real VM stop test)")
        print("REMOVAL_CONTRACT_OK \(passed) checks; fixtures retained at \(root.path)")
    }
}
