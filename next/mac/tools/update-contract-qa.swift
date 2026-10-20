import Foundation

@main struct ContractQA {
    static func main() throws {
        let bundle = URL(fileURLWithPath: CommandLine.arguments[1])
        let release = try WizardRelease.read(bundle)
        try release.validate(bundle)
        print("PASS sealed App/Host native text digests after codesigning")
        let raw = try Data(contentsOf: bundle.appendingPathComponent("Contents/Resources/wizard-release.json"))
        let base = try JSONSerialization.jsonObject(with: raw) as! [String: Any]
        for (name, value) in [("arch", "x86_64" as Any), ("minimumPeer", 99 as Any), ("hostProtocol", 99 as Any), ("schema", 99 as Any), ("build", "001" as Any), ("releaseID", "../../elsewhere" as Any), ("minimumOS", "9999999999999999999999999999.0" as Any), ("guestPatch", "factory-reset" as Any)] {
            var altered = base; altered[name] = value
            let modified = try JSONDecoder().decode(WizardRelease.self, from: JSONSerialization.data(withJSONObject: altered))
            do { try modified.validateMetadata(); throw WizardUpdate.error("TEST FAILED: accepted invalid \(name)") }
            catch { guard !(error.localizedDescription.hasPrefix("TEST FAILED")) else { throw error } }
            print("PASS rejected invalid \(name)")
        }
        var altered = base; var files = altered["files"] as! [String: String]
        files["Contents/MacOS/Wizard"] = String(repeating: "0", count: 64); altered["files"] = files
        let modified = try JSONDecoder().decode(WizardRelease.self, from: JSONSerialization.data(withJSONObject: altered))
        do { try modified.validate(bundle); throw WizardUpdate.error("TEST FAILED: accepted altered code digest") }
        catch { guard !(error.localizedDescription.hasPrefix("TEST FAILED")) else { throw error } }
        print("PASS rejected changed native digest")
    }
}
