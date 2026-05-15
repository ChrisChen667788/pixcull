// swift-tools-version:5.9
//
// P2.1 — PixCull mobile companion app, Swift Package skeleton.
//
// Opens cleanly in Xcode (File → Open → this Package.swift). Builds
// as an iOS-only library plus a sample SwiftUI App target so the
// dev can run on simulator/device without extra scaffolding.
//
// Why a Package vs an .xcodeproj: SPM keeps the source tree
// version-controllable as plain files. Xcode-generated .xcodeproj
// directories carry per-developer cruft that pollutes the repo.

import PackageDescription

let package = Package(
    name: "PixCullCompanion",
    platforms: [
        // iOS 16 is the minimum for SwiftUI 4 (NavigationStack +
        // async-await URLSession on every supported device). PixCull
        // server itself requires Python 3.12, so it's reasonable to
        // assume a modern client device too.
        .iOS(.v16),
    ],
    products: [
        .library(name: "PixCullCompanion",
                 targets: ["PixCullCompanion"]),
    ],
    targets: [
        .target(
            name: "PixCullCompanion",
            path: "Sources/PixCullCompanion",
            resources: []
        ),
    ]
)
