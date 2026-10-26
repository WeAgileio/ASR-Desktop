import AppKit
import ASRDesktopCore
import SwiftUI

@MainActor
private enum BrandAssets {
    private static let bundle: Bundle = {
        if let url = Bundle.main.url(forResource: "ASRDesktop_ASRDesktopApp", withExtension: "bundle"),
           let packaged = Bundle(url: url) { return packaged }
        return .module
    }()
    static let light = NSImage(contentsOf: bundle.url(forResource: "karakuri-mark-light", withExtension: "pdf")!)!
    static let dark = NSImage(contentsOf: bundle.url(forResource: "karakuri-mark-dark", withExtension: "pdf")!)!
}

struct DesktopView: View {
    @Environment(\.colorScheme) private var colorScheme
    @StateObject private var model: DesktopModel
    private let connectsOnAppear: Bool
    init(updates: ReleaseUpdates, model: DesktopModel = DesktopModel(), connectsOnAppear: Bool = true) {
        self.updates = updates
        _model = StateObject(wrappedValue: model)
        self.connectsOnAppear = connectsOnAppear
    }
    @ObservedObject var updates: ReleaseUpdates
    @State private var renameID: String?
    @State private var renameText = ""
    @State private var modelRemoval: [String: Any]?
    @FocusState private var searchFocused: Bool
    @FocusState private var renameFocused: Bool
    private enum FocusTarget: Hashable { case batchActions, batchRow(String), taskRemoval, selectionRemoval, rowRemoval(String), modelRemoval(String) }
    @FocusState private var actionFocus: FocusTarget?
    @State private var renameOrigin: FocusTarget = .batchActions
    @State private var removalOrigin: FocusTarget = .taskRemoval
    @State private var batchMenuFocusRequest = 0

    var body: some View {
        VStack(spacing: 0) {
            if model.pendingCommand != nil {
                Button("重送原請求以確認結果") { model.resendPending() }.disabled(model.busy)
            }
            HStack {
                HStack(spacing: 8) {
                    Image(nsImage: colorScheme == .dark ? BrandAssets.dark : BrandAssets.light)
                        .renderingMode(.original)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 24, height: 24)
                        .accessibilityHidden(true)
                    Text("ASR Desktop").font(.headline)
                }
                if ApplicationPaths().isDevelopmentBuild {
                    Label("開發模式", systemImage: "hammer").foregroundStyle(.secondary)
                }
                Spacer()
                Text(model.connection.rawValue).font(.callout)
                Text(model.queueLabel).font(.callout)
                Button(model.paused ? "恢復佇列" : "暫停佇列") {
                    model.perform(model.paused ? "queue.resume" : "queue.pause")
                }.disabled(model.mutationBlocked)
            }.padding()
            Divider()
            if model.connection != .ready {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Label(model.connection.rawValue, systemImage: "network")
                        Button("啟動／重新連線") { Task { await model.connect() } }
                            .disabled(model.busy || model.connection == .connecting)
                    }
                    if !model.connectionError.isEmpty {
                        DisclosureGroup("連線原因與處理方式") {
                            Text(model.connectionError).textSelection(.enabled)
                            Text("請確認背景服務權限；版本不相容時，停止舊服務並使用相同版本 App 重新連線。")
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }
            TabView(selection: $model.pane) {
                importView.tabItem { Label("匯入", systemImage: "square.and.arrow.down") }.tag(WorkspacePane.intake)
                jobsView.tabItem { Label("任務", systemImage: "list.bullet.rectangle") }.tag(WorkspacePane.jobs)
                modelsView.tabItem { Label("模型", systemImage: "externaldrive") }.tag(WorkspacePane.models)
                settingsView.tabItem { Label("設定", systemImage: "gearshape") }.tag(WorkspacePane.settings)
            }.padding(12)
            Divider()
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                Text(model.feedback[model.pane]?.title ?? "錄好的音訊／影片將在本機處理。")
                    .font(.callout).textSelection(.enabled)
                    .lineLimit(2)
                Spacer()
                Text(updates.currentLabel).font(.callout).fixedSize().accessibilityLabel("目前版本：\(updates.currentLabel)")
                Link("karakuri.tech", destination: URL(string: "https://karakuri.tech")!)
                    .focusable()
                    .font(.callout)
                    .fixedSize()
                    .layoutPriority(1)
                    .accessibilityLabel("karakuri.tech")
                    .accessibilityHint("以預設瀏覽器開啟來源網站")
            }.padding(12)
        }
        .focusedSceneValue(\.workspaceActions, WorkspaceActions(
            openSources: { model.chooseSources() },
            search: { searchFocused = false; model.pane = .jobs; model.returnToList(); Task { @MainActor in await Task.yield(); searchFocused = true } },
            canImport: !model.busy && model.pendingCommand == nil))
        .onChange(of: model.feedback) { oldValue, newValue in
            if let value = newValue[model.pane], oldValue[model.pane] != value, value.kind != .working {
                NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested,
                    userInfo: [.announcement: value.title + "。" + value.message, .priority: NSAccessibilityPriorityLevel.medium.rawValue])
            }
        }
        .onChange(of: modelRemoval?["id"] as? String) { previous, current in
            if current == nil, let previous { restoreFocus(.modelRemoval(previous)) }
        }
        .confirmationDialog("移除模型", isPresented: Binding(get: { modelRemoval != nil }, set: { if !$0 { modelRemoval = nil } }), titleVisibility: .visible) {
            Button("移除模型檔案", role: .destructive) {
                if let item = modelRemoval { model.perform("models.remove", ["id": item["id"] ?? ""]) }
                modelRemoval = nil
            }
            Button("取消", role: .cancel) { modelRemoval = nil }
        } message: {
            Text("移除 \(modelRemoval?["display_name"] as? String ?? "此模型")，目前使用 \(ByteCountFormatter.string(fromByteCount: Int64(modelRemoval?["storage_bytes"] as? Int ?? 0), countStyle: .file))。保留原始影音與成果；日後重試可能需要重新下載。使用中的模型會由服務拒絕移除。")
        }
        .sheet(isPresented: Binding(get: { renameID != nil }, set: { if !$0 { renameID = nil } }), onDismiss: { restoreFocus(renameOrigin) }) {
            VStack(alignment: .leading, spacing: 16) {
                Text("修改批次名稱").font(.headline)
                TextField("名稱", text: $renameText).focused($renameFocused).defaultFocus($renameFocused, true)
                Text("\(renameText.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.count) / 100 Unicode 字元")
                HStack {
                    Button("取消") { renameID = nil }.keyboardShortcut(.cancelAction)
                    Button("儲存") { if let id = renameID { model.perform("batches.rename", ["id": id, "name": renameText]) }; renameID = nil }
                        .keyboardShortcut(.defaultAction)
                        .disabled(model.mutationBlocked || renameText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || renameText.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.count > 100)
                }
            }.padding(24).frame(width: 400)
        }
        .sheet(isPresented: Binding(get: { model.removal != nil }, set: { if !$0 { model.removal = nil } }), onDismiss: { restoreFocus(removalOrigin) }) {
            VStack(alignment: .leading, spacing: 16) {
                Text("移除任務紀錄").font(.headline)
                Text("\(model.removal?["label"] as? String ?? "選取任務")：\(model.removal?["total"] as? Int ?? 0) 筆")
                Text("原始影音檔與已產生的 TXT、SRT、JSON 成果都會保留。移除後，無法從原任務查看詳情或重試。")
                Text("此操作不清理快取或釋放成果空間，且無法復原。")
                HStack {
                    Button("取消") { model.removal = nil }.keyboardShortcut(.cancelAction)
                    Button("移除 \(model.removal?["total"] as? Int ?? 0) 筆紀錄", role: .destructive) {
                        if let value = model.removal {
                            model.perform("jobs.remove", ["selector": value["selector"] ?? [:], "target_token": value["target_token"] ?? ""])
                        }
                        model.removal = nil
                    }.disabled(model.mutationBlocked || (model.removal?["total"] as? Int ?? 0) == 0)
                }
            }.padding(24).frame(width: 460)
        }
        .sheet(isPresented: $updates.showNotice) {
            VStack(alignment: .leading, spacing: 16) {
                Text("有新的 App 版本").font(.title2)
                Text("目前版本：\(updates.currentLabel)")
                if let release = updates.candidate { ReleaseDetailsView(release: release) }
                Text(updates.message).font(.callout)
                HStack {
                    Button("稍後提醒") { updates.later() }.keyboardShortcut(.cancelAction)
                    Button("略過此版本") { updates.skip() }
                    Spacer()
                    Button("前往下載") { updates.openDownload { NSWorkspace.shared.open($0) } }
                        .keyboardShortcut(.defaultAction)
                }
                Text("由你自行下載及安裝，現有轉錄會繼續。")
                    .font(.callout).foregroundStyle(.secondary)
            }.padding(24).frame(width: 480)
        }
        .task { if connectsOnAppear { await updates.check() } }
        .task {
            guard connectsOnAppear else { return }
            await model.connect()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                if !Task.isCancelled { await model.refresh() }
            }
        }
    }

    private func restoreFocus(_ target: FocusTarget) {
        if target == .batchActions {
            batchMenuFocusRequest += 1
            return
        }
        actionFocus = nil
        Task { @MainActor in
            await Task.yield()
            actionFocus = target
        }
    }

    @ViewBuilder private func feedbackView(_ area: WorkspacePane) -> some View {
        if let value = model.feedback[area] {
            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    Label(value.title, systemImage: value.kind == .failure || value.kind == .uncertain ? "exclamationmark.triangle" : "info.circle").font(.headline)
                    ScrollView { Text(value.message).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        .frame(maxHeight: 100).fixedSize(horizontal: false, vertical: true)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(value.title + "。" + value.message)
        }
    }

    private var importView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                feedbackView(.intake)
                Text("加入錄好的音訊與影片").font(.title2.bold())
                GroupBox("1. 來源") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Button("選擇檔案或資料夾") { model.chooseSources() }
                            Button("清除來源") { model.sources = [] }.disabled(model.sources.isEmpty)
                            Toggle("包含子資料夾", isOn: $model.recursive)
                        }
                        Text(model.sources.isEmpty ? "選擇來源，或將檔案／資料夾拖入此區。" : "已加入 \(model.sources.count) 個來源；下方列出展開後的媒體。")
                        if !model.sources.isEmpty {
                            DisclosureGroup("查看來源路徑") {
                                ForEach(Array(model.sources.enumerated()), id: \.offset) { _, url in
                                    Text(url.path).font(.callout).textSelection(.enabled)
                                }
                            }
                        }
                        if model.inspectionReading { ProgressView("正在讀取各檔時長…").controlSize(.small) }
                        ForEach(Array(model.inspection.enumerated()), id: \.offset) { _, entry in
                            mediaEntry(entry, preview: false)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
                .dropDestination(for: URL.self) { urls, _ in
                    guard !model.busy && model.pendingCommand == nil else { return false }
                    model.sources += urls; return true
                }
                GroupBox("2. 本次輸出與辨識設定") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Button("選擇輸出資料夾") { model.chooseOutput() }
                            Text(model.outputDirectory.isEmpty ? "尚未選擇輸出資料夾" : model.outputDirectory).textSelection(.enabled)
                        }
                        Text("這些選項僅用於本次提交，不會儲存為預設值。").font(.callout)
                        Button("套用已儲存預設值") { model.applyDefaults() }.disabled(model.savedDefaults == nil)
                        outputOptions
                        if let item = model.models.first(where: { $0["id"] as? String == model.importDraft.model }), item["state"] as? String != "ready" {
                            Label("指定模型尚未就緒；仍可提交，任務會等待此模型。", systemImage: "exclamationmark.triangle")
                            Button("前往準備 \(model.importDraft.model)") { model.pane = .models }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
                GroupBox("3. 預覽並確認") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Button("預覽批次") { model.inspect() }
                                .disabled(model.sources.isEmpty || model.outputDirectory.isEmpty || model.importDraft.formats.isEmpty || model.previewReading)
                            if model.previewReading { ProgressView().controlSize(.small).accessibilityLabel("正在預覽批次") }
                            Button("提交 \(model.validPreviewCount) 個有效檔案") { model.submit() }
                                .buttonStyle(.borderedProminent).disabled(model.submissionReason != nil || model.mutationBlocked)
                        }
                        if let reason = model.submissionReason { Text(reason).font(.callout) }
                        if model.previewCurrent {
                            Text("有效 \(model.validPreviewCount) 個 · 無效 \(model.preview.count - model.validPreviewCount) 個；僅提交有效檔案。")
                            ForEach(Array(model.preview.enumerated()), id: \.offset) { _, entry in mediaEntry(entry, preview: true) }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
                if model.acceptedBatchID != nil {
                    Button("查看剛提交的批次") { model.viewAcceptedBatch() }
                    if model.connection == .ready && model.paused {
                        Button("恢復佇列") { model.perform("queue.resume") }.disabled(model.mutationBlocked)
                    }
                }
            }.padding(12).disabled(model.busy || model.pendingCommand != nil)
        }
        .onChange(of: model.sources) { model.inspectSources() }
        .onChange(of: model.recursive) { model.inspectSources() }
    }

    private func mediaEntry(_ entry: [String: Any], preview: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            let path = entry["source"] as? String ?? ""
            HStack(alignment: .top) {
                Label(URL(fileURLWithPath: path).lastPathComponent, systemImage: "waveform")
                Spacer()
                Text(MediaDuration.text(entry["duration_ms"] as? Double)).fixedSize()
            }
            if let error = entry["error"] as? String {
                Label(error, systemImage: "exclamationmark.triangle").textSelection(.enabled)
            } else {
                Text(entry["status"] as? String == "valid" ? "可處理" : "時長未知").font(.callout)
            }
            DisclosureGroup(preview ? "來源與輸出計畫" : "完整路徑") {
                Text(path).textSelection(.enabled)
                if preview, let outputs = entry["outputs"] as? [String: String] {
                    ForEach(outputs.keys.sorted(), id: \.self) { format in
                        Text("\(format.uppercased())：\(outputs[format] ?? "")").textSelection(.enabled)
                    }
                }
            }.font(.callout)
            Divider()
        }
    }

    private var outputOptions: some View {
        RecognitionOptionsView(options: $model.importDraft, models: model.models)
    }

    private var jobsView: some View {
        VStack(alignment: .leading, spacing: 8) {
            feedbackView(.jobs)
            GeometryReader { geometry in
                HSplitView {
                    batchSidebar.frame(minWidth: 180, idealWidth: 210, maxWidth: 260)
                    if geometry.size.width >= 1000 {
                        jobList.frame(minWidth: 340, idealWidth: 400)
                        jobInspector.frame(minWidth: 300)
                    } else if model.showingDetail {
                        VStack(alignment: .leading) {
                            Button("返回任務列表", systemImage: "chevron.left") { model.returnToList() }
                            jobInspector
                        }.frame(minWidth: 340)
                    } else {
                        jobList.frame(minWidth: 340)
                    }
                }
            }
        }
    }

    private var batchSidebar: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("批次").font(.headline)
            Button("全部任務") { model.batchID = "" }
                .fontWeight(model.batchID.isEmpty ? .bold : .regular)
            List {
                ForEach(model.batches.compactMap { $0["id"] as? String }, id: \.self) { id in
                    if let batch = model.batches.first(where: { $0["id"] as? String == id }) {
                        Button { model.batchID = id } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(batch["name"] as? String ?? id).lineLimit(2)
                                    .fontWeight(model.batchID == id ? .bold : .regular)
                                Text("\(batch["total"] as? Int ?? 0) 筆 · \(Date(timeIntervalSince1970: batch["created"] as? Double ?? 0).formatted(date: .numeric, time: .shortened))").font(.caption)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }.buttonStyle(.plain)
                        .padding(4).background(model.batchID == id ? Color.accentColor.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 6))
                        .accessibilityValue(model.batchID == id ? "目前批次" : "")
                        .focusable().focused($actionFocus, equals: .batchRow(id))
                        .contextMenu { batchActions(id, name: batch["name"] as? String ?? id, origin: .batchRow(id)) }
                    }
                }
            }
        }.padding(8)
    }

    @ViewBuilder private func batchActions(_ id: String, name: String, origin: FocusTarget = .batchActions) -> some View {
        Button("修改批次名稱") { searchFocused = false; renameOrigin = origin; renameText = name; renameID = id }
        Button("重試此批全部失敗任務（不受篩選限制）") {
            model.perform("jobs.retry", ["selector": ["batch_id": id], "failed_only": true])
        }
        Button("移除此批全部任務紀錄", role: .destructive) { searchFocused = false; removalOrigin = origin; model.previewRemoval(["batch_id": id], label: name) }
    }

    private var jobList: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(model.scopeName).font(.headline).lineLimit(2).help(model.scopeName)
                Spacer()
                if !model.batchID.isEmpty {
                    BatchActionsMenu(focusRequest: batchMenuFocusRequest,
                        rename: { searchFocused = false; renameOrigin = .batchActions; renameText = model.scopeName; renameID = model.batchID },
                        retry: { model.perform("jobs.retry", ["selector": ["batch_id": model.batchID], "failed_only": true]) },
                        remove: { searchFocused = false; removalOrigin = .batchActions; model.previewRemoval(["batch_id": model.batchID], label: model.scopeName) })
                        .frame(width: 130, height: 26).disabled(model.mutationBlocked)
                }
            }
            TextField("搜尋檔名或批次名稱", text: $model.query).focused($searchFocused).accessibilityLabel("搜尋目前範圍的檔名或批次名稱")
            HStack {
                Menu("狀態篩選") {
                    ForEach(["blocked", "queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"], id: \.self) { state in
                        Toggle(stateLabel(state), isOn: Binding(get: { model.states.contains(state) }, set: { if $0 { model.states.insert(state) } else { model.states.remove(state) } }))
                    }
                }
                if !model.query.isEmpty || !model.states.isEmpty { Button("清除條件") { model.clearFilters() } }
            }
            if !model.states.isEmpty { Text("條件：" + model.states.sorted().map { stateLabel($0) }.joined(separator: "、")).font(.callout) }
            Text("範圍共 \(model.counts.values.reduce(0, +)) 筆 · 符合 \(model.total) 筆").font(.callout)
            DisclosureGroup("範圍各狀態數量") {
                Text(model.counts.keys.sorted().map { "\(stateLabel($0)) \(model.counts[$0] ?? 0)" }.joined(separator: " · ")).font(.callout)
            }
            HStack {
                Button("全選符合結果") { model.selectAll() }.disabled(model.total == 0)
                if model.selectedCount > 0 { Button("清除選取") { model.selectedIDs = []; model.allSelection = nil } }
            }
            if model.selectedCount > 0 {
                VStack(alignment: .leading, spacing: 8) {
                    Text("已選 \(model.selectedCount) 筆 · \(model.allSelection == nil ? "個別勾選（可跨頁）" : "全選符合結果（所有頁）")").font(.callout)
                    HStack {
                        Button("重試選取") { model.retrySelection() }
                        Button("移除選取任務紀錄", role: .destructive) { searchFocused = false; removalOrigin = .selectionRemoval; model.previewRemoval(model.currentSelection, label: "選取任務", token: model.allSelection?["target_token"] as? String) }.focusable().focused($actionFocus, equals: .selectionRemoval)
                    }.disabled(model.mutationBlocked)
                }.padding(8).frame(maxWidth: .infinity, alignment: .leading).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
            }
            List {
                ForEach(model.jobs.compactMap { $0["id"] as? String }, id: \.self) { id in
                    if let job = model.jobs.first(where: { $0["id"] as? String == id }) { jobRow(job, id: id) }
                }
                if model.jobs.isEmpty {
                    Text(model.query.isEmpty && model.states.isEmpty ? "此範圍尚無任務，可從匯入加入影音。" : "目前條件沒有符合的任務，請清除或調整條件。")
                }
            }
            HStack {
                Button("上一頁") { model.changePage(max(0, model.offset - 100)) }.disabled(model.offset == 0)
                Text("\(model.offset + (model.total == 0 ? 0 : 1))–\(model.offset + model.jobs.count) / \(model.total)").font(.callout)
                Button("下一頁") { model.changePage(model.offset + 100) }.disabled(model.offset + model.jobs.count >= model.total)
            }
        }.padding(8)
    }

    private func jobRow(_ job: [String: Any], id: String) -> some View {
        let filename = URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent
        let viewing = model.detail?["id"] as? String == id
        return HStack(alignment: .top, spacing: 10) {
            Toggle("選取 \(filename)", isOn: Binding(get: { model.allSelection != nil || model.selectedIDs.contains(id) }, set: { model.setSelected(id, checked: $0) }))
                .toggleStyle(.checkbox).labelsHidden().accessibilityLabel("選取 \(filename)")
            Button { model.showDetail(id) } label: {
                VStack(alignment: .leading, spacing: 6) {
                    Text(filename).lineLimit(2).help(filename)
                    Text("\(stateLabel(job["state"] as? String ?? "")) · \(MediaDuration.text(job["duration_ms"] as? Double))").font(.callout)
                    if job["state"] as? String == "running" {
                        JobProgressView(progress: job["progress"] as? [String: Any] ?? [:], compact: true)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityLabel("查看 \(filename)").accessibilityValue(stateLabel(job["state"] as? String ?? "") + "，" + MediaDuration.text(job["duration_ms"] as? Double) + (viewing ? "，目前查看的任務" : ""))
        }
        .focusable().focused($actionFocus, equals: .rowRemoval(id))
        .padding(6).background(viewing ? Color.accentColor.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 6))
        .contextMenu {
            Button("在 Finder 顯示原始檔") { model.reveal(job, outputs: false) }
            Button("在 Finder 顯示成果") { model.reveal(job, outputs: true) }
            Button("重試此任務") { model.retryJob(id) }
                .disabled(model.mutationBlocked || !["failed", "cancelled", "interrupted"].contains(job["state"] as? String ?? ""))
            Button("移除任務紀錄", role: .destructive) { searchFocused = false; removalOrigin = .rowRemoval(id); model.previewRemoval(["ids": [id]], label: "單筆任務") }.disabled(model.mutationBlocked)
        }
    }

    private var jobInspector: some View {
        ScrollView {
            if let job = model.detail { jobDetail(job) }
            else { Text("選擇任務查看進度與結果；勾選框用於批次操作。").padding(24) }
        }
    }

    private func jobDetail(_ job: [String: Any]) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent).font(.title2.bold()).textSelection(.enabled)
            Label(stateLabel(job["state"] as? String ?? ""), systemImage: "info.circle")
            if model.selectedCount > 0 {
                Text("批次操作已選 \(model.selectedCount) 筆；此任務" + (model.allSelection != nil || model.selectedIDs.contains(job["id"] as? String ?? "") ? "已勾選。" : "未勾選。"))
                    .font(.callout)
            }
            if ["running", "cancelling"].contains(job["state"] as? String ?? "") {
                JobProgressView(progress: job["progress"] as? [String: Any] ?? [:], compact: false)
            }
            if let error = job["error"] as? [String: Any] {
                Label(error["message"] as? String ?? "處理失敗，請檢查來源與模型後重試。", systemImage: "exclamationmark.triangle").textSelection(.enabled)
            }
            ViewThatFits(in: .horizontal) {
                HStack { detailActions(job) }
                VStack(alignment: .leading, spacing: 8) { detailActions(job) }
            }.disabled(model.mutationBlocked)
            if !model.detailStopped && !["running", "queued", "blocked", "completed"].contains(job["state"] as? String ?? "") {
                Text("等待確認執行回收；確認停止後才可重試或移除。").font(.callout)
            }
            Divider()
            Text("實際成果").font(.headline)
            Button("在 Finder 顯示成果") { model.reveal(job, outputs: true) }.disabled(!JobPresentation.hasOutputs(job))
            if !JobPresentation.hasOutputs(job) { Text("尚無可定位的已交付成果。").font(.callout) }
            Text("已交付：" + ((job["delivered_outputs"] as? [String: String] ?? [:]).keys.sorted().joined(separator: "、")))
            Text("尚未交付：" + ((job["undelivered_outputs"] as? [String] ?? []).joined(separator: "、")))
            Text("已遺失：" + ((job["missing_outputs"] as? [String] ?? []).joined(separator: "、")))
            DisclosureGroup("來源與辨識設定") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("媒體時長：" + MediaDuration.text(job["duration_ms"] as? Double))
                    Text("批次：" + (model.batches.first { $0["id"] as? String == job["batch_id"] as? String }?["name"] as? String ?? ""))
                    Text(job["source"] as? String ?? "").textSelection(.enabled)
                    Button("在 Finder 顯示原始檔") { model.reveal(job, outputs: false) }
                    if let options = job["settings"] as? [String: Any] {
                        Text("模型：\(options["model"] as? String ?? "") · 要求裝置：\(options["device"] as? String ?? "auto")")
                    }
                    Text("實際裝置：\(job["actual_device"] as? String ?? "尚未確定")")
                    if let reason = job["device_reason"] as? String { Text(deviceReason(reason)) }
                }.padding(.top, 8)
            }
            DisclosureGroup("輸出計畫（不代表已交付）") {
                if let outputs = job["outputs"] as? [String: String] {
                    ForEach(outputs.keys.sorted(), id: \.self) { format in
                        Text("\(format.uppercased())：\(outputs[format] ?? "")").font(.callout).textSelection(.enabled)
                    }
                }
            }
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private func detailActions(_ job: [String: Any]) -> some View {
        Button("取消任務") { model.perform("jobs.cancel", ["id": job["id"] ?? ""]) }.disabled(!JobPresentation.canCancel(job)).help("僅等待或執行中任務可取消")
        Button("重試") { if let id = job["id"] as? String { model.retryJob(id) } }
            .disabled(!JobPresentation.canRetry(job, stopped: model.detailStopped)).help("僅已停止的失敗、取消或中斷任務可重試")
        Button("移除任務紀錄", role: .destructive) { searchFocused = false; removalOrigin = .taskRemoval; model.previewRemoval(["ids": [job["id"] ?? ""]], label: "單筆任務") }.focusable().focused($actionFocus, equals: .taskRemoval)
            .disabled(!JobPresentation.canRemove(job, stopped: model.detailStopped)).help("需等待任務停止及回收，再確認移除")
    }

    private func deviceReason(_ reason: String) -> String {
        ["insufficient_evidence": "自動：尚無合格比較證據，使用 CPU",
         "incomplete_profile_identity": "環境資料不完整，保守使用 CPU",
         "explicit_device": "依明確裝置設定執行",
         "gpu_combination_quarantined": "此 GPU 組合需重新校準，目前使用 CPU",
         "qualified_gpu_improvement": "合格比較顯示 GPU 至少快 10%",
         "gpu_below_improvement_threshold": "GPU 比較未達升級門檻，使用 CPU",
         "mps_compatibility_cpu_fallback": "GPU 相容性失敗，本次已改用 CPU"][reason] ?? "依本機裝置政策執行"
    }

    private var modelsView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    feedbackView(.models)
                    Text("本機辨識模型").font(.title2.bold())
                    Text("全部資產驗證完成才會就緒，準備完成後可離線使用。")
                    if model.models.isEmpty { Text("尚未取得模型清單，請確認服務連線。") }
                    ForEach(model.models.compactMap { $0["id"] as? String }, id: \.self) { id in
                        if let item = model.models.first(where: { $0["id"] as? String == id }) { modelCard(item).id(id) }
                    }
                }.padding(20)
            }.onAppear { proxy.scrollTo(model.importDraft.model, anchor: .top) }
        }
    }

    private func modelCard(_ item: [String: Any]) -> some View {
        let state = item["state"] as? String ?? "missing"
        let preparing = ["downloading", "verifying"].contains(state)
        return GroupBox(item["display_name"] as? String ?? item["id"] as? String ?? "模型") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(stateLabel(state), systemImage: state == "ready" ? "checkmark.circle" : "externaldrive")
                    if item["id"] as? String == model.importDraft.model { Text("本次匯入選用").font(.callout) }
                }
                Text("下載量：\(ByteCountFormatter.string(fromByteCount: Int64(item["download_bytes"] as? Int ?? 0), countStyle: .file))")
                Text("準備所需可用空間：\(ByteCountFormatter.string(fromByteCount: Int64(item["required_free_bytes"] as? Int ?? 0), countStyle: .file))")
                if preparing {
                    if let current = item["downloaded_bytes"] as? Double, let total = item["total_bytes"] as? Double,
                       current.isFinite, total.isFinite, current >= 0, total > 0 {
                        ProgressView(value: min(current, total), total: total)
                    } else { ProgressView(state == "verifying" ? "正在驗證完整性…" : "正在準備下載…").controlSize(.small) }
                }
                if let error = item["error"] as? [String: Any] { Label(error["message"] as? String ?? "模型準備失敗，請重試。", systemImage: "exclamationmark.triangle").textSelection(.enabled) }
                if !preparing && state != "ready" {
                    Button(state == "missing" ? "下載模型" : "重試／修復模型") { model.perform("models.download", ["id": item["id"] ?? ""]) }
                        .buttonStyle(.borderedProminent).disabled(model.mutationBlocked)
                }
                DisclosureGroup("電腦需求與維護") {
                    VStack(alignment: .leading, spacing: 10) {
                        if let requirements = item["requirements"] as? [String: String] {
                            ForEach(["platform", "cpu", "gpu", "minimum_memory", "recommended_memory", "notes"], id: \.self) { key in
                                if let value = requirements[key] { Text(value).textSelection(.enabled) }
                            }
                            if let source = requirements["source"], let url = URL(string: source) { Link("模型文件／需求依據", destination: url) }
                        }
                        Text("目前使用：\(ByteCountFormatter.string(fromByteCount: Int64(item["storage_bytes"] as? Int ?? 0), countStyle: .file))")
                        HStack {
                            Button("重新驗證") { model.perform("models.verify", ["id": item["id"] ?? ""]) }
                            Button("移除模型…", role: .destructive) { modelRemoval = item }.focusable().focused($actionFocus, equals: .modelRemoval(item["id"] as? String ?? ""))
                        }.disabled(preparing || model.mutationBlocked)
                    }.padding(.top, 8)
                }
            }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var settingsView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                feedbackView(.settings)
                GroupBox("新任務的預設值") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(model.defaultsSummary.isEmpty ? "尚未載入已儲存預設值" : model.defaultsSummary).textSelection(.enabled)
                        Text("保存後供後續新任務使用，不改動目前匯入或已接受的任務。")
                        if model.settingsDirty { Label("尚有未儲存修改", systemImage: "pencil") }
                        if model.defaultsChanged { Text("預設值由其他客戶端更新；目前保留你的草稿。") }
                        RecognitionOptionsView(options: $model.settingsDraft, models: model.models).disabled(model.busy || model.pendingCommand != nil)
                        if model.settingsDraft.formats.isEmpty { Text("請至少選擇一種輸出格式。") }
                        HStack {
                            Button("儲存預設值") { model.perform("settings.set", ["settings": model.settingsDraft.dictionary]) }
                                .buttonStyle(.borderedProminent).disabled(model.savedDefaults == nil || model.settingsDraft.formats.isEmpty || model.mutationBlocked)
                            Button("重新載入已儲存值") { model.reloadSettings() }.disabled(model.savedDefaults == nil || model.busy)
                        }
                    }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("裝置與校準") {
                    VStack(alignment: .leading, spacing: 12) {
                        Button("選擇樣本並校準 CPU／GPU") {
                            let panel = NSOpenPanel()
                            panel.canChooseFiles = true; panel.canChooseDirectories = false
                            if panel.runModal() == .OK, let url = panel.url {
                                model.perform("device.calibrate", ["paths": [url.path], "settings": ["model": model.settingsDraft.model]])
                            }
                        }.disabled(model.mutationBlocked)
                        Text("校準模型：\(model.settingsDraft.model)。使用同一佇列依序測試 CPU 與 GPU；沒有合格品質與資源證據時，自動仍使用 CPU。")
                    }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("背景服務與診斷") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("關閉視窗後，已接受的工作仍會繼續。停止服務會先暫停領取，再等目前工作完成。")
                        HStack {
                            Button("啟動／重新連線") { Task { await model.connect() } }.disabled(model.busy || model.connection == .connecting)
                            Button("停止背景服務") { model.perform("service.stop") }.disabled(model.mutationBlocked)
                            Button("診斷安裝") { diagnose() }.disabled(model.busy)
                        }
                    }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                }
                UpdateSettingsView(updates: updates)
                GroupBox("CLI 工具") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("建立命令連結後，仍需自行確認 ~/.local/bin 已在 PATH。")
                        Button("安裝 CLI 連結") {
                            do { model.report(.settings, "CLI 連結", "已建立 \(try CommandLink.install().path)", .success) }
                            catch { model.report(.settings, "CLI 連結失敗", error.localizedDescription) }
                        }.disabled(model.busy)
                    }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(20)
        }
    }

    private func diagnose() {
        model.busy = true
        Task {
            defer { model.busy = false }
            do {
                let result = try await Task.detached { try RuntimeDiagnostics.run() }.value
                model.report(.settings, "安裝診斷", result.status == 0 ? "內建 runtime、FunASR 與媒體工具實際診斷通過" : "內建環境無法完整執行，請重新安裝完整且相符版本的 App。", result.status == 0 ? .success : .failure)
            } catch { model.report(.settings, "安裝診斷失敗", "請重新安裝完整 App：" + error.localizedDescription) }
        }
    }

    private func stateLabel(_ state: String) -> String {
        ["queued": "等待執行", "blocked": "等待指定模型", "running": "處理中", "completed": "完成", "failed": "失敗",
         "cancelled": "已取消", "cancelling": "正在取消", "interrupted": "已中斷，需明確重試", "ready": "已就緒",
         "missing": "尚未下載", "downloading": "下載中", "verifying": "驗證中", "corrupt": "需要修復"][state] ?? state
    }
}
