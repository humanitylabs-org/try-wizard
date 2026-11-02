import Foundation

@main
struct FilesFolderTests {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let defaults = UserDefaults(suiteName: WizardShared.appBundleID)!
        let previous = defaults.string(forKey: "DataHome")
        defaults.set(root.path, forKey: "DataHome")
        defer {
            if let previous { defaults.set(previous, forKey: "DataHome") }
            else { defaults.removeObject(forKey: "DataHome") }
        }
        let expected = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Wizard MVP")
        precondition(WizardShared.defaultFilesFolder.path == expected.path)
        precondition(WizardShared.supportDir == root)
        precondition(WizardShared.filesFolder == nil)
        let old = root.appendingPathComponent("Files", isDirectory: true)
        try FileManager.default.createDirectory(at: old, withIntermediateDirectories: true)
        let sentinel = old.appendingPathComponent("existing-document.txt")
        try "preserve existing files".write(to: sentinel, atomically: true, encoding: .utf8)
        try WizardShared.setFilesFolder(old)
        precondition(WizardShared.filesFolder == old)
        _ = WizardShared.defaultFilesFolder
        precondition(WizardShared.filesFolder == old)
        let preserved = try String(contentsOf: sentinel)
        precondition(preserved == "preserve existing files")
        let custom = root.appendingPathComponent("Custom Chosen Folder", isDirectory: true)
        try WizardShared.setFilesFolder(custom)
        precondition(WizardShared.filesFolder == custom)
        let preservedAfterCustom = try String(contentsOf: sentinel)
        precondition(preservedAfterCustom == "preserve existing files")
        print("FILES_FOLDER_DEFAULT_AND_EXISTING_SELECTION_PASS")
    }
}
