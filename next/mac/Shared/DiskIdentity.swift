import Foundation
import Darwin

/// Cooperating App/Host processes serialize all disk-identity decisions and writes.
final class WizardDiskOwnership {
    private var fd: Int32 = -1
    func acquire() throws {
        guard fd < 0 else { return }
        let url = WizardShared.osDir.appendingPathComponent("disk-owner.lock")
        fd = open(url.path, O_CREAT | O_RDWR, 0o600)
        guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            if fd >= 0 { close(fd); fd = -1 }
            throw WizardUpdate.error("Another process owns this Wizard disk")
        }
    }
    func release() { if fd >= 0 { flock(fd, LOCK_UN); close(fd); fd = -1 } }
    deinit { release() }
}

enum WizardDiskIdentity {
    static func read(_ disk: URL) -> String? {
        guard let a = try? FileManager.default.attributesOfItem(atPath: disk.path),
              a[.type] as? FileAttributeType == .typeRegular,
              let device = a[.systemNumber], let inode = a[.systemFileNumber] else { return nil }
        return "\(device):\(inode)"
    }
    /// Caller holds WizardDiskOwnership. No unknown/missing identity is authority.
    static func requireColdOwner(_ journal: [String: Any]) throws {
        guard journal["kind"] as? String == "legacy-cold" else { return }
        guard journal["dataHome"] as? String == WizardShared.supportDir.path,
              let identity = read(WizardShared.osDir.appendingPathComponent("disk.img")),
              journal["diskIdentity"] as? String == identity else {
            throw WizardUpdate.error("Cold transaction disk identity changed; current disk and rollback copy left untouched")
        }
    }
    static func completed(_ completion: [String: Any], modern: [String: Any], journal: [String: Any], disk: URL, home: URL) -> Bool {
        guard let identity = read(disk) else { return false }
        if completion["diskIdentity"] as? String == identity { return true }
        // A guest response alone is not a host disk receipt. Bind both records to
        // the stopped disk and transaction; stale legacy-cold journals cannot let
        // a replacement legacy disk reach ordinary boot.
        return modern["managed_runtime_image"] as? String != nil
            && modern["diskIdentity"] as? String == identity
            && journal["diskIdentity"] as? String == identity
            && journal["dataHome"] as? String == home.path
            && journal["phase"] as? String == "guest-activated"
            && (journal["nonce"] as? String).map { !$0.isEmpty && modern["transactionNonce"] as? String == $0 } == true
    }
    /// Never mint a success receipt for whichever disk happens to be present.
    static func completionRecord(_ journal: [String: Any]) throws -> [String: Any] {
        try requireColdOwner(journal)
        guard journal["kind"] as? String == "legacy-cold", journal["phase"] as? String == "guest-activated",
              let identity = journal["diskIdentity"] as? String,
              let release = journal["releaseID"] as? String else {
            throw WizardUpdate.error("Cold completion does not match the activated transaction")
        }
        return ["diskIdentity": identity, "releaseID": release]
    }
}
