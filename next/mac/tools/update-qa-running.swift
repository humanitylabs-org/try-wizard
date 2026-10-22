import AppKit
import Foundation
let apps = NSWorkspace.shared.runningApplications.filter { ($0.bundleIdentifier ?? "").hasPrefix("org.humanitylabs.wizard") }
let rows: [[String: Any]] = apps.map { ["pid": $0.processIdentifier, "bundleID": $0.bundleIdentifier ?? "", "bundleURL": $0.bundleURL?.path ?? "", "terminated": $0.isTerminated] }
print(String(data: try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted,.sortedKeys]), encoding: .utf8)!)
