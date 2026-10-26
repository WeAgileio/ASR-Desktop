import SwiftUI

struct WorkspaceActions {
    var openSources: () -> Void
    var search: () -> Void
    var canImport: Bool
}

private struct WorkspaceActionsKey: FocusedValueKey {
    typealias Value = WorkspaceActions
}

extension FocusedValues {
    var workspaceActions: WorkspaceActions? {
        get { self[WorkspaceActionsKey.self] }
        set { self[WorkspaceActionsKey.self] = newValue }
    }
}

struct WorkspaceCommands: Commands {
    @FocusedValue(\.workspaceActions) private var actions
    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("加入音訊、影片或資料夾…") { actions?.openSources() }
                .keyboardShortcut("o").disabled(actions?.canImport != true)
        }
        CommandGroup(after: .textEditing) {
            Button("搜尋任務") { actions?.search() }
                .keyboardShortcut("f").disabled(actions == nil)
        }
    }
}
