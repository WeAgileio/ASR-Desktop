import AppKit
import ASRDesktopCore
import SwiftUI

struct UpdateSettingsView: View {
    @ObservedObject var updates: ReleaseUpdates
    var body: some View {
        GroupBox("App 版本與更新") {
            VStack(alignment: .leading, spacing: 12) {
                Text("目前版本：\(updates.currentLabel)").textSelection(.enabled)
                Toggle("啟動時自動檢查更新（最多每 24 小時一次）", isOn: Binding(
                    get: { updates.automatic }, set: { updates.setAutomatic($0) }))
                HStack {
                    Button("檢查更新") { Task { await updates.check(manual: true) } }
                        .disabled(updates.checking)
                    if updates.checking { ProgressView().controlSize(.small).accessibilityLabel("正在檢查更新") }
                    Text(updates.message).textSelection(.enabled)
                }
                if let date = updates.lastSuccess {
                    Text("最後成功檢查：\(date.formatted())").foregroundStyle(.secondary)
                }
                if let release = updates.candidate {
                    ReleaseDetailsView(release: release)
                    HStack {
                        Button("前往下載") { updates.openDownload { NSWorkspace.shared.open($0) } }
                        Button("略過此版本") { updates.skip() }
                    }
                }
                Text("開啟 GitHub Release 頁後，由你自行下載及安裝。更新檢查不會停止轉錄。")
                    .font(.callout).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
        }
    }
}

struct ReleaseDetailsView: View {
    let release: DesktopRelease
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("可用版本：\(release.version?.tag ?? release.tag_name)（\(release.prerelease ? "測試版" : "正式版")）")
                .font(.headline)
            ScrollView { Text(verbatim: release.notes).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                .frame(maxHeight: 160)
        }
    }
}
