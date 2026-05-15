// P2.1 — SwiftUI App entry point.
//
// Wired as a public type so a host iOS .xcodeproj can use it as
// the @main entry. When opened as a Package directly in Xcode,
// Xcode generates a wrapper that finds this @main automatically.

import SwiftUI

@main
public struct PixCullCompanionApp: App {
    public init() {}

    public var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
