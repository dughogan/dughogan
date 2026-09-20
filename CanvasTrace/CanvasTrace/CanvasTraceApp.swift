import SwiftUI

@main
struct CanvasTraceApp: App {
    @StateObject private var settings = OverlaySettings()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .preferredColorScheme(.dark)
        }
    }
}
