// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "WizardBackupContract",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "WizardBackupContract", path: "Shared", exclude: ["Shared.swift"], sources: ["BackupContract.swift", "DownloadDestinations.swift"]),
        .testTarget(name: "WizardBackupContractTests", dependencies: ["WizardBackupContract"], path: "Tests/Backup"),
        .target(name: "WizardRollbackRetirement", path: "Shared", exclude: ["Shared.swift"], sources: ["RollbackRetirement.swift"]),
        .testTarget(name: "WizardRollbackRetirementTests", dependencies: ["WizardRollbackRetirement"], path: "Tests/RollbackRetirement")
    ],
    swiftLanguageModes: [.v5]
)
