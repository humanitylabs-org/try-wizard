import AppKit
import WebKit

/// A page's authority and navigation state never follow the active defaults index.
final class WizardPage {
    let backend: Backend
    let web: WKWebView
    var homeURL: URL?
    var resolvedOrigins = Set<String>()
    var loadedAt: Date?
    var header = NSRect.zero
    var controls: [NSRect] = []
    init(backend: Backend, web: WKWebView) { self.backend = backend; self.web = web }
}

extension WizardWindowController {
    static func makeWorkspaceWebView() -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = UserDefaults.standard.bool(forKey: "QAHooks") && UserDefaults.standard.bool(forKey: "QAWebStorage") ? .nonPersistent() : .default()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        cfg.userContentController.add(NativeBridge.shared, name: NativeBridge.name)
        for script in [MeetingBridge.adapterJS, WizardDragView.script, WorkspaceCapability.script] {
            cfg.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        let web = WKWebView(frame: .zero, configuration: cfg)
        web.setValue(false, forKey: "drawsBackground")
        web.allowsBackForwardNavigationGestures = false
        return web
    }
    func attachWorkspaceWebView(_ page: WKWebView) {
        page.navigationDelegate = self; page.uiDelegate = self
        page.translatesAutoresizingMaskIntoConstraints = false
        pageContainer.addSubview(page)
        NSLayoutConstraint.activate([page.leadingAnchor.constraint(equalTo: pageContainer.leadingAnchor),
                                     page.trailingAnchor.constraint(equalTo: pageContainer.trailingAnchor),
                                     page.topAnchor.constraint(equalTo: pageContainer.topAnchor),
                                     page.bottomAnchor.constraint(equalTo: pageContainer.bottomAnchor)])
    }
    func page(for web: WKWebView) -> WizardPage? { pages.values.first { $0.web === web } }
    func activateWorkspacePage() {
        guard let backend = Store.active, shownWorkspaceID != backend.id else { return }
        if let old = currentPage { old.header = dragView.header; old.controls = dragView.controls }
        web.isHidden = true
        if let page = pages[backend.id] { web = page.web }
        else {
            // Reuse the never-navigated startup view; all subsequent views are lazy.
            if shownWorkspaceID != nil { web = Self.makeWorkspaceWebView(); attachWorkspaceWebView(web) }
            pages[backend.id] = WizardPage(backend: backend, web: web)
        }
        shownWorkspaceID = backend.id; pagePolicy.visit(backend.id)
        web.isHidden = updateFrozen
        dragView.header = currentPage?.header ?? .zero; dragView.controls = currentPage?.controls ?? []
        window?.makeFirstResponder(web)
        evictWorkspacePages()
    }
    func evictWorkspacePages() {
        let pinned = Set(pages.values.filter { $0.backend.kind == .thisMac }.map { $0.backend.id })
        for id in pagePolicy.evictions(active: shownWorkspaceID ?? "", loaded: Set(pages.keys), pinned: pinned) {
            discardWorkspacePage(id)
        }
    }
    func discardWorkspacePage(_ id: String) {
        guard let page = pages.removeValue(forKey: id) else { return }
        page.web.stopLoading(); page.web.navigationDelegate = nil; page.web.uiDelegate = nil
        page.web.configuration.userContentController.removeScriptMessageHandler(forName: NativeBridge.name)
        page.web.removeFromSuperview(); pagePolicy.remove(id)
    }
    func switchWorkspace(_ id: String) throws {
        let start = ProcessInfo.processInfo.systemUptime
        guard !updateFrozen, !WizardUpdater.shared.isPreparing else { throw OSInstaller.error("Wait for the local update to finish.") }
        try Store.workspaces.select(id)
        let cached = pages[id]?.loadedAt != nil
        clearLocalVoice(); activateWorkspacePage()
        WizardBindings.refresh(origin: nativeControlURL)
        WizardSearch.shared.workspaceChanged()
        if cached {
            overlay.isHidden = true
            if Store.active?.kind == .thisMac { startLocalVoice() }
            onNavigate()
            // Recompute drag regions in the resumed document after layout changes.
            web.evaluateJavaScript("window.dispatchEvent(new Event('resize'))")
        } else { begin() }
        pageContainer.layoutSubtreeIfNeeded()
        lastWorkspaceSwitchMilliseconds = (ProcessInfo.processInfo.systemUptime - start) * 1000
        workspacesChanged()
    }
    func installWorkspaceBridge() {
        NativeBridge.shared.register("workspaces.") { [weak self] method, params, reply in
            guard let self else { reply(["ok": false, "error": "Wizard window closed."]); return }
            do {
                switch method {
                case "workspaces.list": reply(self.workspaceSnapshot)
                case "workspaces.switch":
                    try self.switchWorkspace(params["id"] as? String ?? ""); reply(["ok": true])
                case "workspaces.rename":
                    try Store.workspaces.rename(params["id"] as? String ?? "", to: params["name"] as? String ?? "")
                    self.workspacesChanged(); reply(["ok": true])
                case "workspaces.remove":
                    guard !self.updateFrozen, !WizardUpdater.shared.isPreparing else { throw OSInstaller.error("Wait for the local update to finish.") }
                    let id = params["id"] as? String ?? ""
                    try Store.workspaces.remove(id)
                    if self.shownWorkspaceID == id, let active = Store.active { try self.switchWorkspace(active.id) }
                    // Deliver the reply before dismantling the calling document.
                    reply(["ok": true]); self.workspacesChanged()
                    DispatchQueue.main.async { self.discardWorkspacePage(id) }
                case "workspaces.add":
                    guard !self.updateFrozen, !WizardUpdater.shared.isPreparing else { throw OSInstaller.error("Wait for the local update to finish.") }
                    reply(["ok": true])
                    DispatchQueue.main.async { self.addWorkspace() }
                default: reply(["ok": false, "error": "Unknown workspace method."])
                }
            } catch { reply(["ok": false, "error": error.localizedDescription]) }
        }
        workspaceTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in self?.probeWorkspaceStatuses() }
        probeWorkspaceStatuses()
    }
    func addWorkspace() {
        guard !updateFrozen, !WizardUpdater.shared.isPreparing else { return }
        let alert = NSAlert()
        alert.messageText = "Add a Wizard"
        alert.informativeText = "Run your own Wizard on this Mac, or connect to one on another computer."
        alert.addButton(withTitle: "Run Wizard on This Mac")
        alert.addButton(withTitle: "Connect to Another Computer…")
        alert.addButton(withTitle: "Cancel")
        guard let window else { return }
        alert.beginSheetModal(for: window) { [weak self] result in
            if result == .alertFirstButtonReturn { self?.chooseThisMac() }
            if result == .alertSecondButtonReturn { self?.chooseRemote() }
        }
    }
    var workspaceSnapshot: [String: Any] {
        ["active": Store.active?.id ?? "", "items": Store.backends.map { b -> [String: Any] in
            var item: [String: Any] = ["id": b.id, "name": b.name, "kind": b.kind.bridgeValue,
                                      "url": b.url, "status": workspaceStatuses[b.id] ?? "unknown"]
            if let subtitle = b.subtitle { item["subtitle"] = subtitle }
            return item
        }]
    }
    func workspacesChanged() {
        (NSApp.delegate as? AppDelegate)?.rebuildWizardMenu()
        let detail = workspaceSnapshot
        for page in pages.values where isTrustedDocument(page.web) {
            page.web.callAsyncJavaScript("window.dispatchEvent(new CustomEvent('wizard:workspaces', {detail}));",
                                         arguments: ["detail": detail], in: nil, in: .page) { _ in }
        }
        probeWorkspaceStatuses()
    }
    func setWorkspaceStatus(_ id: String, _ status: String) {
        guard Store.backends.contains(where: { $0.id == id }), workspaceStatuses[id] != status else { return }
        workspaceStatuses[id] = status
        workspacesChanged()
    }
    func probeWorkspaceStatuses() {
        for b in Store.backends {
            if b.kind == .thisMac {
                let state = WizardUpdate.json(WizardShared.statusFile)["state"] as? String ?? "unknown"
                let status: String
                switch state {
                case "running": status = "ready"
                case "starting", "stopping": status = "starting"
                case "stopped", "notInstalled", "error": status = "offline"
                default: status = "unknown"
                }
                // No recursive notification/probe cycle.
                if workspaceStatuses[b.id] != status {
                    workspaceStatuses[b.id] = status
                    DispatchQueue.main.async { [weak self] in self?.workspacesChanged() }
                }
                continue
            }
            guard workspaceProbeTasks[b.id] == nil, (workspaceProbeDue[b.id] ?? .distantPast) <= Date(),
                  let url = URL(string: b.url), ["https", "http"].contains(url.scheme ?? "") else { continue }
            var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
            request.httpMethod = "HEAD" // Reachability only, never a remote admin operation.
            let id = b.id
            workspaceProbeTasks[id] = URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.workspaceProbeTasks[id] = nil
                    let ready = response is HTTPURLResponse // Even 401/403 means the Wizard is reachable.
                    let failures = ready ? 0 : (self.workspaceProbeFailures[id] ?? 0) + 1
                    self.workspaceProbeFailures[id] = failures
                    self.workspaceProbeDue[id] = Date().addingTimeInterval(WorkspaceProbePolicy.delay(failures: failures))
                    self.setWorkspaceStatus(id, ready ? "ready" : "offline")
                }
            }
            workspaceProbeTasks[id]?.resume()
        }
        let saved = Set(Store.backends.map(\.id))
        for id in Array(workspaceProbeTasks.keys) where !saved.contains(id) { workspaceProbeTasks.removeValue(forKey: id)?.cancel() }
    }
    func controlOrigins(for backend: Backend) -> Set<NativeOrigin> {
        let urls: [URL]
        if backend.kind == .thisMac {
            urls = [WizardShared.localSetupURL, URL(string: "http://127.0.0.1:\(WizardShared.uxPort)/")!]
        } else { urls = URL(string: backend.url).map { [$0] } ?? [] }
        return Set(urls.compactMap(NativeOrigin.init).filter { !$0.isInstalledApp })
    }
    func isTrustedDocument(_ view: WKWebView) -> Bool {
        guard let page = page(for: view), let actual = view.url.flatMap(NativeOrigin.init), !actual.isInstalledApp else { return false }
        // Existing local-voice fixture authority remains scoped to the ACTIVE view.
        if view === web { return isTrustedDocument }
        return controlOrigins(for: page.backend).contains(actual)
    }
    func allowsNative(_ frame: WKFrameInfo, in view: WKWebView) -> Bool {
        guard frame.isMainFrame, isTrustedDocument(view), let origin = NativeOrigin(frame.securityOrigin) else { return false }
        return view.url.flatMap(NativeOrigin.init) == origin
    }
}
