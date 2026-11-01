import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// All destructive inputs and OS effects are injected. No ambient Wizard paths or defaults here.
struct WizardRemovalPlan {
    enum Action: String { case keepData, deleteData, startFresh }
    struct Entry { let label: String; let url: URL }
    let action: Action
    let home: URL
    let library: URL
    let dataHome: URL
    let app: URL
    let files: [URL]
    let bundleIDs: [String]
    var removesData: Bool { action != .keepData }
    var removesApp: Bool { action != .startFresh }
    var entries: [Entry] { removesData ? inventory : [] }
    var inventory: [Entry] { // Also used for the before/after Keep inventory.

        var result = [Entry(label: "Wizard data (disk, chats, sign-ins, apps and logs)", url: dataHome)]
        for id in bundleIDs {
            result.append(Entry(label: "Preferences (\(id))", url: library.appendingPathComponent("Preferences/\(id).plist")))
            for kind in ["Caches", "WebKit", "HTTPStorages"] {
                result.append(Entry(label: "\(kind) (\(id))", url: library.appendingPathComponent("\(kind)/\(id)")))
            }
        }
        return result
    }
    static func error(_ message: String) -> NSError {
        NSError(domain: "WizardRemoval", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    static func contains(_ parent: URL, _ child: URL) -> Bool {
        let p = parent.standardizedFileURL.path, c = child.standardizedFileURL.path
        return p == c || c.hasPrefix(p == "/" ? "/" : p + "/")
    }
    static func overlaps(_ a: URL, _ b: URL) -> Bool { contains(a, b) || contains(b, a) }
    func validate() throws {
        guard !files.isEmpty, !bundleIDs.isEmpty,
              Set(bundleIDs).count == bundleIDs.count,
              bundleIDs.allSatisfy({ $0.range(of: "^[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$", options: .regularExpression) != nil }),
              app.pathExtension == "app" else { throw Self.error("The removal paths could not be verified. Nothing was removed.") }
        let targets = inventory.map(\.url) + [app]
        let roots = [URL(fileURLWithPath: "/"), home, library,
                     home.appendingPathComponent("Documents"), home.appendingPathComponent("Desktop"),
                     home.appendingPathComponent("Downloads"), URL(fileURLWithPath: "/Applications"),
                     URL(fileURLWithPath: "/Volumes"), URL(fileURLWithPath: "/Library"),
                     URL(fileURLWithPath: "/System"), URL(fileURLWithPath: "/usr"),
                     URL(fileURLWithPath: "/bin"), URL(fileURLWithPath: "/sbin"),
                     URL(fileURLWithPath: "/private"), URL(fileURLWithPath: "/opt")]
            + (FileManager.default.mountedVolumeURLs(includingResourceValuesForKeys: nil, options: []) ?? [])
        for target in targets {
            let resolved = target.resolvingSymlinksInPath().standardizedFileURL
            // A selected Files folder inside OR around a target is unsafe, even through a symlink.
            for folder in files {
                if Self.overlaps(target, folder) || Self.overlaps(resolved, folder.resolvingSymlinksInPath()) {
                    throw Self.error("Your Files folder overlaps \(target.path). Move it outside Wizard's app and data folders first. Nothing was removed.")
                }
            }
            if roots.contains(where: { Self.contains(resolved, $0.resolvingSymlinksInPath()) }) {
                throw Self.error("Refusing to remove a shared system or home folder: \(target.path)")
            }
            // Never follow a redirected deletion target, including a symlinked ancestor.
            guard target.standardizedFileURL.path == resolved.path else {
                throw Self.error("A removal path is a symbolic link: \(target.path). Nothing was removed.")
            }
        }
        guard !Self.overlaps(dataHome.resolvingSymlinksInPath(), app.resolvingSymlinksInPath()) else {
            throw Self.error("Wizard's app and data folders overlap. Nothing was removed.")
        }
        if removesData {
            for entry in entries.dropFirst() where Self.overlaps(dataHome, entry.url) {
                throw Self.error("The data folder overlaps macOS settings. Nothing was removed.")
            }
        }
    }
    /// Allocated bytes, not the virtual length of the sparse 64-GiB disk. Links are not followed.
    static func allocatedBytes(_ url: URL) -> Int64 {
        let fm = FileManager.default
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isSymbolicLinkKey, .totalFileAllocatedSizeKey, .fileAllocatedSizeKey]
        func bytes(_ u: URL) -> Int64 {
            guard let v = try? u.resourceValues(forKeys: keys), v.isSymbolicLink != true else { return 0 }
            return Int64(v.totalFileAllocatedSize ?? v.fileAllocatedSize ?? 0)
        }
        var result = bytes(url)
        if let e = fm.enumerator(at: url, includingPropertiesForKeys: Array(keys)) {
            for case let u as URL in e { result += bytes(u) }
        }
        return result
    }
}

struct WizardRemovalEffects {
    var remove: (URL) throws -> Void
    var clearPreferences: (String) throws -> Void
    var resetPrivacy: (String) throws -> Void
    var trash: (URL) throws -> Void
    var clone: (URL, URL) throws -> Void
}

enum WizardRemoval {
    /// Caller holds exclusive disk ownership for the entire operation. Recheck stop/path fences at every effect.
    static func execute(_ plan: WizardRemovalPlan, isStopped: () -> Bool,
                        backup: URL? = nil, effects: WizardRemovalEffects) throws {
        func fence() throws {
            guard isStopped() else { throw WizardRemovalPlan.error("Wizard OS is not confirmed stopped. Nothing else was removed.") }
            try plan.validate()
        }
        try fence()
        if let backup {
            guard plan.action == .startFresh,
                  !WizardRemovalPlan.overlaps(backup, plan.dataHome),
                  !WizardRemovalPlan.overlaps(backup, plan.app),
                  !plan.files.contains(where: { WizardRemovalPlan.overlaps(backup, $0) || WizardRemovalPlan.overlaps(backup.resolvingSymlinksInPath(), $0.resolvingSymlinksInPath()) }),
                  backup.standardizedFileURL.path == backup.resolvingSymlinksInPath().standardizedFileURL.path,
                  !FileManager.default.fileExists(atPath: backup.path) else {
                throw WizardRemovalPlan.error("Choose a new backup folder outside Wizard data and your Files folder.")
            }
            try effects.clone(plan.dataHome.appendingPathComponent("os"), backup)
        }
        // Clear CFPreferences as well as the plist; cfprefsd would otherwise put old values back.
        if plan.removesData {
            // Retain the external DataHome pointer until its deletion succeeds. Reset privacy last:
            // revoking removable-volume access first can prevent removing the selected external disk.
            for entry in plan.entries where entry.url != plan.dataHome && !entry.url.path.hasSuffix(".plist") {
                try fence(); try effects.remove(entry.url)
            }
            try fence(); try effects.remove(plan.dataHome)
            for id in plan.bundleIDs { try fence(); try effects.clearPreferences(id) }
            for entry in plan.entries where entry.url.path.hasSuffix(".plist") { try fence(); try effects.remove(entry.url) }
            for id in plan.bundleIDs { try fence(); try effects.resetPrivacy(id) }
        }
        if plan.removesApp { try fence(); try effects.trash(plan.app) }
    }
}

/// Watch the ORIGINAL app path, not Bundle.main.bundleURL after Finder has moved it.
struct WizardMissingAppWatch {
    let originalApp: URL
    func isMissing(fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> Bool {
        !fileExists(originalApp.appendingPathComponent("Contents/Info.plist").path)
    }
}
