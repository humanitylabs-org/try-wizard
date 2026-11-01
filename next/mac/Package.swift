// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "WizardBackupContract",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "WizardBackupContract", path: "Shared", exclude: ["Shared.swift"], sources: ["BackupContract.swift", "WorkspaceStore.swift"]),
        .testTarget(name: "WizardBackupContractTests", dependencies: ["WizardBackupContract"], path: "Tests/Backup"),
        .testTarget(name: "WizardWorkspaceTests", dependencies: ["WizardBackupContract"], path: "Tests/Workspaces", exclude: ["fixture.cjs"])
    ],
    swiftLanguageModes: [.v5]
)
