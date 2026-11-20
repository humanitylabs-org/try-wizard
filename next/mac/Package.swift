// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "WizardBackupContract",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "WizardBackupContract", path: "Shared", exclude: ["Shared.swift"], sources: ["BackupContract.swift", "DownloadDestinations.swift", "FrontDoorHandoff.swift"]),
        .testTarget(name: "WizardBackupContractTests", dependencies: ["WizardBackupContract"], path: "Tests/Backup"),
        .target(name: "WizardRollbackRetirement", path: "Shared", exclude: ["Shared.swift"], sources: ["RollbackRetirement.swift"]),
        .testTarget(name: "WizardRollbackRetirementTests", dependencies: ["WizardRollbackRetirement"], path: "Tests/RollbackRetirement"),
        .target(name: "WizardBundleName", path: "Shared", exclude: ["Shared.swift"], sources: ["BundleName.swift"]),
        .testTarget(name: "WizardBundleNameTests", dependencies: ["WizardBundleName"], path: "Tests/BundleName"),
        .target(name: "WizardHostHandover", path: "Shared", exclude: ["Shared.swift"], sources: ["HostHandover.swift"]),
        .testTarget(name: "WizardHostHandoverTests", dependencies: ["WizardHostHandover"], path: "Tests/HostHandover"),
        .target(name: "WizardAppLocation", path: "Shared", exclude: ["Shared.swift"], sources: ["AppLocation.swift"]),
        .testTarget(name: "WizardAppLocationTests", dependencies: ["WizardAppLocation"], path: "Tests/AppLocation"),
        .target(name: "WizardNowPlaying", path: "Shared", exclude: ["Shared.swift"], sources: ["NowPlaying.swift"]),
        .testTarget(name: "WizardNowPlayingTests", dependencies: ["WizardNowPlaying"], path: "Tests/NowPlaying")
    ],
    swiftLanguageModes: [.v5]
)
