import ASRDesktopCore
import SwiftUI

@main
struct ASRDesktopApp: App {
    @StateObject private var updates = ReleaseUpdates()
    init() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments.count == 2 && arguments[0] == "--service-control" {
            let (data, status) = ServiceRegistration.perform(arguments[1])
            FileHandle.standardOutput.write(data)
            exit(status)
        }
    }

    var body: some Scene {
        WindowGroup("ASR Desktop") {
            DesktopView(updates: updates)
                .frame(minWidth: 860, minHeight: 640)
        }
        .defaultSize(width: 1040, height: 740)
    }
}
