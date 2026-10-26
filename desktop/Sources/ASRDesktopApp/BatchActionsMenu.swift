import AppKit
import SwiftUI

/// NSPopUpButton supports returning first responder after a modal sheet on macOS.
struct BatchActionsMenu: NSViewRepresentable {
    @Environment(\.isEnabled) private var isEnabled
    var focusRequest: Int
    var rename: () -> Void
    var retry: () -> Void
    var remove: () -> Void

    final class Button: NSPopUpButton {
        override var acceptsFirstResponder: Bool { true }
    }

    @MainActor final class Coordinator: NSObject {
        var owner: BatchActionsMenu
        var lastFocusRequest: Int
        init(_ owner: BatchActionsMenu) {
            self.owner = owner; lastFocusRequest = owner.focusRequest
        }
        @objc func choose(_ sender: NSPopUpButton) {
            switch sender.indexOfSelectedItem {
            case 1: owner.rename()
            case 2: owner.retry()
            case 3: owner.remove()
            default: break
            }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> Button {
        let button = Button(frame: .zero, pullsDown: true)
        button.bezelStyle = .rounded
        button.addItems(withTitles: ["此批次操作", "修改批次名稱",
            "重試此批全部失敗任務（不受篩選限制）", "移除此批全部任務紀錄"])
        button.setAccessibilityLabel("此批次操作")
        button.target = context.coordinator
        button.action = #selector(Coordinator.choose(_:))
        return button
    }

    func updateNSView(_ button: Button, context: Context) {
        context.coordinator.owner = self
        button.isEnabled = isEnabled
        if context.coordinator.lastFocusRequest != focusRequest {
            context.coordinator.lastFocusRequest = focusRequest
            Task { @MainActor [weak button] in
                await Task.yield()
                guard let button else { return }
                button.window?.makeFirstResponder(button)
            }
        }
    }
}
