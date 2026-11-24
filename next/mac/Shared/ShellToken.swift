import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// wizard-os#133: with the browser boundary on, a Wizard's owner routes (the Agent Service) answer only calls that
/// carry the shell-only token in `X-Wizard-Shell-Token`; anything else gets 401 `shell_token_required`. The Wizard
/// writes that token into its shell page for a real top-level page load only (the shell's nginx, wizard-ux
/// packaging/entrypoint.sh), which is how the Mac window's shell gets it, and the shell keeps it from app frames.
///
/// The app's own native calls to owner routes (dictation) get it the same way the window does: one page load of that
/// same Wizard's shell. The token is kept in memory only (never on disk, never logged) and is only ever sent back to
/// the origin it came from. A Wizard with the boundary off answers the calls as before, so nothing changes there.
enum WizardShellToken {
    static let header = "X-Wizard-Shell-Token"
    /// The shell page (index.html) every Wizard serves; the Mac window opens the same entry (resolveHome).
    static let pagePath = "/wizard-os-home/"

    /// `scheme://host:port` of a URL (lowercased, default port filled in), or nil for anything but http(s).
    static func originKey(_ url: URL?) -> String? {
        guard let url, let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = url.host?.lowercased(), !host.isEmpty, url.user == nil, url.password == nil else { return nil }
        let port = url.port ?? (scheme == "https" ? 443 : 80)
        return "\(scheme)://\(host):\(port)"
    }

    /// The page load that carries the token: what a browser sends for a top-level navigation (nginx writes the
    /// token only for `navigate` + `document`). Never cached, no cookies.
    static func pageRequest(origin: URL) -> URLRequest? {
        guard originKey(origin) != nil, var c = URLComponents(url: origin, resolvingAgainstBaseURL: false) else { return nil }
        c.path = pagePath; c.query = nil; c.fragment = nil
        guard let url = c.url else { return nil }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        req.httpShouldHandleCookies = false
        req.setValue("text/html", forHTTPHeaderField: "Accept")
        req.setValue("navigate", forHTTPHeaderField: "Sec-Fetch-Mode")
        req.setValue("document", forHTTPHeaderField: "Sec-Fetch-Dest")
        req.setValue("none", forHTTPHeaderField: "Sec-Fetch-Site")
        return req
    }

    /// The token in a shell page, or nil: `off` (the boundary is off), empty, or anything but 64 lowercase hex.
    static func parse(_ page: Data?) -> String? {
        guard let page, let html = String(data: page.prefix(256 * 1024), encoding: .utf8),
              let re = try? NSRegularExpression(pattern: "<meta\\s+name=\"wizard-shell-token\"\\s+content=\"([0-9a-f]{64})\"\\s*/?>") else { return nil }
        let range = NSRange(html.startIndex..., in: html)
        guard let m = re.firstMatch(in: html, range: range), let r = Range(m.range(at: 1), in: html) else { return nil }
        return String(html[r])
    }

    /// The Agent Service's browser-boundary refusal (and only that one): 401 {"error": "shell_token_required"}.
    static func refused(status: Int?, body: Data?) -> Bool {
        guard status == 401, let body,
              let j = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] else { return false }
        return j["error"] as? String == "shell_token_required"
    }

    /// `request` with the token for its own origin, when one is known.
    static func withToken(_ request: URLRequest, _ token: String?) -> URLRequest {
        guard let token else { return request }
        var r = request; r.setValue(token, forHTTPHeaderField: header); return r
    }

    private static let queue = DispatchQueue(label: "org.humanitylabs.wizard.shell-token")
    private static var tokens: [String: String] = [:]
    static func cached(_ key: String) -> String? { queue.sync { tokens[key] } }
    static func remember(_ key: String, _ token: String?) { queue.sync { tokens[key] = token } }

    /// Reads the token from `origin`'s shell page. nil when the page is not that origin's (a redirect elsewhere), not
    /// a 200, or carries no token (boundary off).
    static func fetch(origin: URL, session: URLSession = .shared, _ done: @escaping (String?) -> Void) {
        guard let key = originKey(origin), let req = pageRequest(origin: origin) else { done(nil); return }
        session.dataTask(with: req) { data, response, _ in
            let http = response as? HTTPURLResponse
            guard http?.statusCode == 200, originKey(http?.url) == key, let token = parse(data) else { done(nil); return }
            remember(key, token)
            done(token)
        }.resume()
    }

    /// Sends a native owner call. With a token known for the request's origin it rides along; when the Wizard refuses
    /// the call for want of one (boundary on, or the token changed), the token is read again from that Wizard's shell
    /// page and the call is sent once more. Any other answer is handed back unchanged.
    static func send(_ request: URLRequest, session: URLSession = .shared,
                     _ done: @escaping (Data?, URLResponse?, Error?) -> Void) {
        guard let key = originKey(request.url), let origin = request.url else {
            session.dataTask(with: request, completionHandler: done).resume(); return
        }
        let had = cached(key)
        session.dataTask(with: withToken(request, had)) { data, response, error in
            guard refused(status: (response as? HTTPURLResponse)?.statusCode, body: data) else { done(data, response, error); return }
            fetch(origin: origin, session: session) { token in
                guard let token, token != had else { done(data, response, error); return }
                session.dataTask(with: withToken(request, token), completionHandler: done).resume()
            }
        }.resume()
    }
}
