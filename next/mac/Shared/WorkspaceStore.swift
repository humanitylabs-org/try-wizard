import Foundation

/// Keep the original kind spellings in defaults: 0.7.0 decodes thisMac/remote.
struct Backend: Codable, Equatable {
    enum Kind: String, Codable {
        case thisMac, remote, company, managed
        var bridgeValue: String { self == .thisMac ? "this-mac" : rawValue }
    }
    var kind: Kind
    var name: String
    var url: String
    var id: String = UUID().uuidString
    var subtitle: String? = nil
    enum CodingKeys: String, CodingKey { case kind, name, url, id, subtitle }
    init(kind: Kind, name: String, url: String, id: String = UUID().uuidString, subtitle: String? = nil) {
        self.kind = kind; self.name = name; self.url = url; self.id = id; self.subtitle = subtitle
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decode(Kind.self, forKey: .kind)
        name = try c.decode(String.self, forKey: .name)
        url = try c.decode(String.self, forKey: .url)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? UUID().uuidString
        subtitle = try c.decodeIfPresent(String.self, forKey: .subtitle)
    }
}

/// The old keys and array order remain authoritative; migration only adds IDs.
final class WorkspaceRegistry {
    let defaults: UserDefaults
    init(defaults: UserDefaults) { self.defaults = defaults }
    var backends: [Backend] {
        get {
            guard let data = defaults.data(forKey: "backends"),
                  var items = try? JSONDecoder().decode([Backend].self, from: data) else { return [] }
            let raw = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] ?? []
            var seen = Set<String>()
            var changed = raw.contains { ($0["id"] as? String)?.isEmpty != false }
            for i in items.indices {
                if items[i].id.isEmpty || !seen.insert(items[i].id).inserted {
                    items[i].id = UUID().uuidString; seen.insert(items[i].id); changed = true
                }
            }
            if changed { backends = items }
            return items
        }
        set { defaults.set(try? JSONEncoder().encode(newValue), forKey: "backends") }
    }
    var activeIndex: Int {
        get { let i = defaults.integer(forKey: "activeBackend"); return backends.indices.contains(i) ? i : 0 }
        set { defaults.set(newValue, forKey: "activeBackend") }
    }
    var active: Backend? { let items = backends; return items.indices.contains(activeIndex) ? items[activeIndex] : items.first }
    @discardableResult func add(_ backend: Backend) -> String {
        var items = backends
        if let i = items.firstIndex(where: { backend.kind == .thisMac ? $0.kind == .thisMac : $0.url == backend.url }) {
            activeIndex = i; return items[i].id
        }
        items.append(backend); backends = items; activeIndex = items.count - 1; return backend.id
    }
    func select(_ id: String) throws {
        guard let i = backends.firstIndex(where: { $0.id == id }) else { throw failure("That Wizard is no longer saved.") }
        activeIndex = i
    }
    func rename(_ id: String, to name: String) throws {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 120 else { throw failure("Use a name between 1 and 120 characters.") }
        var items = backends
        guard let i = items.firstIndex(where: { $0.id == id }) else { throw failure("That Wizard is no longer saved.") }
        items[i].name = name; backends = items
    }
    func remove(_ id: String) throws {
        var items = backends
        guard let i = items.firstIndex(where: { $0.id == id }) else { throw failure("That Wizard is no longer saved.") }
        guard items.count > 1 else { throw failure("Keep at least one Wizard.") }
        let selected = active?.id
        items.remove(at: i); backends = items
        activeIndex = items.firstIndex(where: { $0.id == selected }) ?? min(i, items.count - 1)
        // Forgetting an entry deliberately has no VM, filesystem or network side effects.
    }
    private func failure(_ text: String) -> NSError { NSError(domain: "WizardWorkspaces", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
}

/// At most four BACKGROUND pages, plus the active page. Local pages are pinned:
/// their capture state must remain available to the updater's fail-closed guard.
struct WorkspacePagePolicy {
    private(set) var recent: [String] = []
    mutating func visit(_ id: String) { recent.removeAll { $0 == id }; recent.append(id) }
    mutating func remove(_ id: String) { recent.removeAll { $0 == id } }
    func evictions(active: String, loaded: Set<String>, pinned: Set<String> = []) -> [String] {
        let background = recent.filter { loaded.contains($0) && $0 != active }
        var excess = max(0, background.count - 4)
        return background.filter { id in
            guard excess > 0, !pinned.contains(id) else { return false }
            excess -= 1; return true
        }
    }
}

/// Exponential failed-probe backoff, never faster than 30 seconds.
struct WorkspaceProbePolicy {
    static func delay(failures: Int) -> TimeInterval { min(300, 30 * pow(2, Double(min(max(failures, 0), 4)))) }
}

/// Reassignment by bridge.handle must merge the native capability, not erase it.
enum WorkspaceCapability {
    static let script = """
    (() => {
      window.wizardNativeCaps = Object.assign(window.wizardNativeCaps || {}, {workspaces:true});
      const merge = value => {
        const ux = value && typeof value === 'object' ? value : {};
        ux.native = Object.assign(ux.native || {}, {workspaces:true});
        return ux;
      };
      let ux = merge(window.wizardUX);
      Object.defineProperty(window, 'wizardUX', {configurable:true, enumerable:true,
        get:()=>ux, set:value=>{ux=merge(value);}});
    })();
    """
}
