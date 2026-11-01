import XCTest
@testable import WizardBackupContract

final class WorkspaceTests: XCTestCase {
    var defaults: UserDefaults!
    var registry: WorkspaceRegistry!
    var domain: String!
    override func setUp() {
        domain = "org.humanitylabs.wizard.tests.workspaces." + UUID().uuidString
        defaults = UserDefaults(suiteName: domain)!
        registry = WorkspaceRegistry(defaults: defaults)
    }
    override func tearDown() { defaults.removePersistentDomain(forName: domain) }
    func remote(_ n: String) -> Backend { Backend(kind: .remote, name: n, url: "https://\(n).example/wizard/") }
    func testAddSelectsAndDeduplicatesWithoutLosingNamesOrIDs() {
        let a = remote("one"); let b = remote("two")
        XCTAssertEqual(registry.add(a), a.id); registry.add(b)
        XCTAssertEqual(registry.active?.id, b.id)
        var duplicate = a; duplicate.name = "do not overwrite"
        XCTAssertEqual(registry.add(duplicate), a.id)
        XCTAssertEqual(registry.backends, [a, b]); XCTAssertEqual(registry.active?.id, a.id)
    }
    func testSwitchAndUnknownID() throws {
        let a = remote("one"); let b = remote("two"); registry.add(a); registry.add(b)
        try registry.select(a.id)
        XCTAssertEqual(registry.active?.id, a.id)
        XCTAssertThrowsError(try registry.select("absent")); XCTAssertEqual(registry.active?.id, a.id)
    }
    func testRenameTrimsAndPersistsAcrossRegistryRecreation() throws {
        let a = remote("one"); registry.add(a)
        try registry.rename(a.id, to: " My Wizard \n")
        XCTAssertEqual(WorkspaceRegistry(defaults: defaults).active?.name, "My Wizard")
        XCTAssertEqual(registry.active?.url, a.url)
    }
    func testInvalidRenameDoesNotChangeStore() {
        let a = remote("one"); registry.add(a)
        XCTAssertThrowsError(try registry.rename(a.id, to: " \n"))
        XCTAssertThrowsError(try registry.rename(a.id, to: String(repeating: "x", count: 121)))
        XCTAssertThrowsError(try registry.rename("absent", to: "name"))
        XCTAssertEqual(registry.active, a)
    }
    func testRemovePreservesActiveIDWhenEarlierEntryRemoved() throws {
        let a = remote("one"); let b = remote("two"); registry.add(a); registry.add(b)
        try registry.remove(a.id)
        XCTAssertEqual(registry.active, b); XCTAssertEqual(registry.activeIndex, 0)
    }
    func testRemoveActiveSelectsSurvivor() throws {
        let a = remote("one"); let b = remote("two"); registry.add(a); registry.add(b)
        try registry.remove(b.id)
        XCTAssertEqual(registry.active, a)
        XCTAssertThrowsError(try registry.remove("missing"))
    }
    func testLastEntryRemovalRefusedByteForByte() {
        let a = remote("one"); registry.add(a)
        let before = defaults.data(forKey: "backends")
        XCTAssertThrowsError(try registry.remove(a.id))
        XCTAssertEqual(defaults.data(forKey: "backends"), before)
        XCTAssertEqual(registry.active, a)
    }
    func testLocalDedupPreservesOriginalOrderAndFriendlyName() {
        let a = Backend(kind: .thisMac, name: "Wizard on this Mac", url: "http://127.0.0.1:48030/")
        registry.add(a); registry.add(remote("two"))
        registry.add(Backend(kind: .thisMac, name: "other", url: "http://localhost:48030/"))
        XCTAssertEqual(registry.backends.count, 2); XCTAssertEqual(registry.active, a)
    }
    func testLegacy070MigrationKeepsFieldsOrderAndSelectedIndex() throws {
        let data = Data(#"[{"kind":"thisMac","name":"This Mac","url":"http://127.0.0.1:48030/"},{"kind":"remote","name":"Private Name","url":"https://example.invalid/custom/?keep=yes"}]"#.utf8)
        defaults.set(data, forKey: "backends"); defaults.set(1, forKey: "activeBackend")
        let items = registry.backends
        XCTAssertEqual(items.map(\.name), ["This Mac", "Private Name"])
        XCTAssertEqual(items.map(\.kind), [.thisMac, .remote])
        XCTAssertEqual(items[1].url, "https://example.invalid/custom/?keep=yes")
        XCTAssertEqual(registry.active?.id, items[1].id)
        XCTAssertEqual(WorkspaceRegistry(defaults: defaults).backends, items)
        let raw = try XCTUnwrap(try JSONSerialization.jsonObject(with: XCTUnwrap(defaults.data(forKey: "backends"))) as? [[String: Any]])
        XCTAssertEqual(raw[0]["kind"] as? String, "thisMac")
        struct OldBackend: Decodable { var kind: String; var name: String; var url: String }
        let old = try JSONDecoder().decode([OldBackend].self, from: XCTUnwrap(defaults.data(forKey: "backends")))
        XCTAssertEqual(old.map(\.name), items.map(\.name))
    }
    func testBadIndexAndDuplicateIDMigration() {
        let a = remote("one"); var b = remote("two"); b.id = a.id
        registry.backends = [a, b]; defaults.set(900, forKey: "activeBackend")
        XCTAssertEqual(registry.active?.id, a.id)
        XCTAssertNotEqual(registry.backends[0].id, registry.backends[1].id)
        XCTAssertEqual(Set(registry.backends.map(\.id)).count, 2)
    }
    func testCompanyAndManagedKindsRoundTripAndBridgeSpelling() throws {
        let a = Backend(kind: .company, name: "Team", url: "https://company.example", subtitle: "Member")
        let b = Backend(kind: .managed, name: "Person", url: "https://managed.example", subtitle: "Technical Admin")
        registry.backends = [a, b]
        XCTAssertEqual(registry.backends, [a, b])
        XCTAssertEqual(Backend.Kind.thisMac.bridgeValue, "this-mac")
    }
    func testEvictionKeepsFourBackgroundAndActive() {
        var policy = WorkspacePagePolicy()
        for id in ["a", "b", "c", "d", "e", "f"] { policy.visit(id) }
        let loaded = Set(policy.recent)
        XCTAssertEqual(policy.evictions(active: "f", loaded: loaded), ["a"])
        policy.visit("a")
        XCTAssertEqual(policy.evictions(active: "a", loaded: loaded), ["b"])
        policy.remove("b")
        XCTAssertEqual(policy.evictions(active: "a", loaded: loaded.subtracting(["b"])), [])
    }
    func testLocalActivityPagePinnedDuringEviction() {
        var policy = WorkspacePagePolicy()
        for id in ["local", "b", "c", "d", "e", "active"] { policy.visit(id) }
        XCTAssertEqual(policy.evictions(active: "active", loaded: Set(policy.recent), pinned: ["local"]), ["b"])
    }
    func testProbeBackoffBounded() {
        XCTAssertEqual(WorkspaceProbePolicy.delay(failures: 0), 30)
        XCTAssertEqual(WorkspaceProbePolicy.delay(failures: 1), 60)
        XCTAssertEqual(WorkspaceProbePolicy.delay(failures: 99), 300)
        XCTAssertEqual(WorkspaceProbePolicy.delay(failures: -1), 30)
    }
}
