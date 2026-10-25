import AppKit
import ASRDesktopCore
import SwiftUI

@MainActor
final class DesktopModel: ObservableObject {
    @Published var jobs: [[String: Any]] = []
    @Published var models: [[String: Any]] = []
    @Published var paused = true
    @Published var message = ""
    @Published var sources: [URL] = []
    @Published var outputDirectory = ""
    @Published var recursive = false
    @Published var selectedModel = "fun-asr-nano"
    @Published var device = "auto"
    @Published var script = "traditional"
    @Published var includeJSON = false
    @Published var includeTXT = true
    @Published var includeSRT = true
    @Published var language = "中文"
    @Published var hotwords = ""
    @Published var maxChars = 20
    @Published var maxDuration = 5000
    @Published var offset = 0
    @Published var total = 0
    @Published var counts: [String: Int] = [:]
    @Published var defaultsSummary = ""
    @Published var overwrite = false
    @Published var preview: [[String: Any]] = []
    @Published var busy = false
    @Published var serviceStopped = false
    @Published var pendingCommand: PendingCommand?
    @Published var batches: [[String: Any]] = []
    @Published var batchID = "" { didSet { if oldValue != batchID { queryChanged() } } }
    @Published var query = "" { didSet { if oldValue != query { queryChanged() } } }
    @Published var states: Set<String> = [] { didSet { if oldValue != states { queryChanged() } } }
    @Published var selectedIDs: Set<String> = []
    @Published var allSelection: [String: Any]?
    @Published var detail: [String: Any]?
    @Published var removal: [String: Any]?
    @Published var inspection: [[String: Any]] = []
    @Published var inspectionReading = false
    @Published var compatible = false
    private var queryState = QueryState()
    private var searchTask: Task<Void, Never>?
    private var inspectionTask: Task<Void, Never>?
    private var inspectionGeneration = 0
    private var detailGeneration = 0
    private var savedDefaults: [String: Any] = [:]

    func connect() async {
        do {
            try await Task.detached { try ServiceClient.ensureReady() }.value
            serviceStopped = false
            let status = try await call("service.status") as? [String: Any] ?? [:]
            compatible = TaskCapabilities.supports(status["capabilities"] as? [String] ?? [])
            guard compatible else { message = "背景服務缺少任務管理能力，請使用相同版本 App 並重新啟動服務。"; return }
            await refresh()
        } catch { message = error.localizedDescription }
    }

    func call(_ operation: String, _ arguments: [String: Any] = [:]) async throws -> Any {
        let encoded = try JSONSerialization.data(withJSONObject: arguments)
        let data = try await Task.detached {
            let decoded = try JSONSerialization.jsonObject(with: encoded) as? [String: Any] ?? [:]
            return try ControlSocket.request(operation, arguments: decoded)
        }.value
        guard let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ControlSocket.ControlError.invalidResponse
        }
        if envelope["success"] as? Bool != true {
            let error = envelope["error"] as? [String: Any]
            throw NSError(domain: "ASRDesktop", code: 3, userInfo: ["serviceCode": error?["code"] as? String ?? "", NSLocalizedDescriptionKey: error?["message"] as? String ?? "操作失敗，請檢查背景服務與模型狀態。"])
        }
        return envelope["result"] ?? [:]
    }

    var selector: [String: Any] {
        var result: [String: Any] = ["query": query, "states": states.sorted()]
        if !batchID.isEmpty { result["batch_id"] = batchID }
        return result
    }
    var scopeName: String { batches.first { $0["id"] as? String == batchID }?["name"] as? String ?? "全部任務" }
    var selectedCount: Int { allSelection?["total"] as? Int ?? selectedIDs.count }
    var currentSelection: [String: Any] { allSelection?["selector"] as? [String: Any] ?? ["ids": selectedIDs.sorted()] }

    func changePage(_ value: Int) {
        offset = value; queryState.change()
        Task { await refresh() }
    }

    func queryChanged() {
        detailGeneration += 1
        offset = 0; selectedIDs = []; allSelection = nil; detail = nil
        queryState.change()
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(250))
            if !Task.isCancelled { await refresh() }
        }
    }

    func refresh() async {
        guard !serviceStopped && compatible, let generation = queryState.begin() else { return }
        do {
            var arguments = selector; arguments["offset"] = offset; arguments["limit"] = 100
            let page = try await call("jobs.list", arguments) as? [String: Any] ?? [:]
            if queryState.accepts(generation) {
                let updatedJobs = page["jobs"] as? [[String: Any]] ?? []
                if !NSArray(array: jobs).isEqual(to: updatedJobs) { jobs = updatedJobs }
                paused = page["queue_paused"] as? Bool ?? true
                total = page["total"] as? Int ?? jobs.count
                counts = page["scope_counts"] as? [String: Int] ?? [:]
                if offset > 0 && offset >= total { offset = max(0, ((total - 1) / 100) * 100); queryState.change() }
            }
            var allBatches: [[String: Any]] = []
            var batchOffset = 0
            repeat {
                let page = try await call("batches.list", ["offset": batchOffset, "limit": 500]) as? [String: Any] ?? [:]
                let items = page["batches"] as? [[String: Any]] ?? []
                allBatches += items; batchOffset += items.count
                if batchOffset >= (page["total"] as? Int ?? 0) || items.isEmpty { break }
            } while true
            if !NSArray(array: batches).isEqual(to: allBatches) { batches = allBatches }
            if !batchID.isEmpty && !batches.contains(where: { $0["id"] as? String == batchID }) { batchID = "" }
            if queryState.accepts(generation), let id = detail?["id"] as? String {
                let detailVersion = detailGeneration
                do {
                    let value = try await call("jobs.show", ["id": id]) as? [String: Any]
                    if queryState.accepts(generation) && detailVersion == detailGeneration { detail = value }
                } catch { if detailVersion == detailGeneration { detail = nil } }
            }
            if queryState.accepts(generation) && !selectedIDs.isEmpty {
                let ids = selectedIDs
                var retained = Set<String>()
                var scanOffset = 0
                repeat {
                    var arguments = selector; arguments["offset"] = scanOffset; arguments["limit"] = 500
                    let page = try await call("jobs.list", arguments) as? [String: Any] ?? [:]
                    guard queryState.accepts(generation) else { break }
                    let rows = page["jobs"] as? [[String: Any]] ?? []
                    retained.formUnion(rows.compactMap { $0["id"] as? String })
                    scanOffset += rows.count
                    if scanOffset >= (page["total"] as? Int ?? 0) || rows.isEmpty { break }
                } while true
                if queryState.accepts(generation) { selectedIDs.subtract(ids.subtracting(retained)) }
            }
            if queryState.accepts(generation), let selection = allSelection {
                do { _ = try await call("jobs.selection.preview", ["selector": selection["selector"] ?? [:], "target_token": selection["target_token"] ?? ""]) }
                catch {
                    if queryState.accepts(generation) { allSelection = nil; message = "選取目標已變更，請重新選取及確認。" }
                }
            }
            models = try await call("models.list") as? [[String: Any]] ?? []
            if let defaults = try await call("settings.show") as? [String: Any] { syncDefaults(defaults) }
        } catch { message = error.localizedDescription }
        let again = queryState.finish()
        if again { await refresh() }
    }

    func showDetail(_ id: String) {
        detailGeneration += 1
        let generation = detailGeneration
        Task {
            do {
                let value = try await call("jobs.show", ["id": id]) as? [String: Any]
                if generation == detailGeneration { detail = value }
            } catch { if generation == detailGeneration { detail = nil; message = error.localizedDescription } }
        }
    }
    func selectAll() {
        let captured = selector
        Task {
            do {
                let result = try await call("jobs.selection.preview", ["selector": captured]) as? [String: Any]
                if NSDictionary(dictionary: captured).isEqual(to: selector) { allSelection = result; selectedIDs = [] }
            } catch { message = error.localizedDescription }
        }
    }
    func retrySelection() {
        var arguments: [String: Any] = ["selector": currentSelection]
        if let token = allSelection?["target_token"] { arguments["target_token"] = token }
        perform("jobs.retry", arguments)
    }
    func previewRemoval(_ selector: [String: Any], label: String, token: String? = nil) {
        Task {
            do {
                var args: [String: Any] = ["selector": selector]
                if let token { args["target_token"] = token }
                var value = try await call("jobs.selection.preview", args) as? [String: Any] ?? [:]
                if !(value["cannot_remove"] as? [[String: Any]] ?? []).isEmpty {
                    message = "有任務仍執行、取消中或尚未回收；請先停止並等待，再重新確認。"; return
                }
                value["label"] = label; removal = value
            } catch { message = error.localizedDescription; allSelection = nil }
        }
    }
    func reveal(_ job: [String: Any], outputs: Bool) {
        Task {
            do {
                if outputs {
                    let value = try await call("jobs.show", ["id": job["id"] ?? ""]) as? [String: Any] ?? [:]
                    let paths = value["delivered_outputs"] as? [String: String] ?? [:]
                    if paths.isEmpty && !(value["missing_outputs"] as? [String] ?? []).isEmpty { throw FinderLocation.LocationError.missing }
                    try FinderLocation.reveal(Array(paths.values).sorted())
                } else { try FinderLocation.reveal([job["source"] as? String ?? ""]) }
            } catch { message = error.localizedDescription }
        }
    }

    func inspectSources() {
        inspectionGeneration += 1
        let generation = inspectionGeneration
        inspectionTask?.cancel(); inspection = []; preview = []
        guard !sources.isEmpty else { inspectionReading = false; return }
        inspectionReading = true
        let args: [String: Any] = ["paths": sources.map(\.path), "recursive": recursive]
        inspectionTask = Task {
            defer { if generation == inspectionGeneration { inspectionReading = false } }
            do {
                var started: [String: Any] = [:]
                while !Task.isCancelled && generation == inspectionGeneration {
                    do { started = try await call("intake.inspect", args) as? [String: Any] ?? [:]; break }
                    catch {
                        guard (error as NSError).userInfo["serviceCode"] as? String == "inspection_busy" else { throw error }
                        try await Task.sleep(for: .milliseconds(300))
                    }
                }
                guard let id = started["id"] as? String else { return }
                while !Task.isCancelled && generation == inspectionGeneration {
                    let result = try await call("intake.inspect", ["id": id]) as? [String: Any] ?? [:]
                    if generation != inspectionGeneration || Task.isCancelled { return }
                    if result["state"] as? String == "complete" {
                        inspection = result["entries"] as? [[String: Any]] ?? []; return
                    }
                    try await Task.sleep(for: .milliseconds(300))
                }
            } catch { if generation == inspectionGeneration && !Task.isCancelled { message = error.localizedDescription } }
        }
    }

    private func syncDefaults(_ defaults: [String: Any]) {
        let keys = Set(options.keys)
        func canonical(_ value: [String: Any]) -> Data? {
            try? JSONSerialization.data(withJSONObject: value.filter { keys.contains($0.key) }, options: [.sortedKeys])
        }
        let clean = savedDefaults.isEmpty || canonical(options) == canonical(savedDefaults)
        let changed = canonical(savedDefaults) != canonical(defaults)
        savedDefaults = defaults
        defaultsSummary = "已儲存：\(defaults["model"] as? String ?? "") · \(defaults["device"] as? String ?? "") · \(defaults["script"] as? String ?? "")"
        guard changed else { return }
        if clean {
            selectedModel = defaults["model"] as? String ?? "fun-asr-nano"
            let value = defaults["device"] as? String ?? "auto"
            device = value == "mps" ? "gpu" : value
            script = defaults["script"] as? String ?? "traditional"
            let formats = defaults["formats"] as? [String] ?? ["txt", "srt"]
            includeTXT = formats.contains("txt"); includeSRT = formats.contains("srt"); includeJSON = formats.contains("json")
            language = defaults["language"] as? String ?? "中文"
            hotwords = (defaults["hotwords"] as? [String] ?? []).joined(separator: ", ")
            maxChars = defaults["max_chars"] as? Int ?? 20
            maxDuration = defaults["max_duration_ms"] as? Int ?? 5000
            overwrite = defaults["overwrite"] as? Bool ?? false
        } else if canonical(options) != canonical(defaults) {
            message = "已儲存的預設值已更新；此表單保留尚未儲存的選項。"
        }
    }

    var options: [String: Any] {
        ["model": selectedModel, "device": device, "script": script,
         "formats": (includeTXT ? ["txt"] : []) + (includeSRT ? ["srt"] : []) + (includeJSON ? ["json"] : []),
         "overwrite": overwrite, "language": language,
         "hotwords": hotwords.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty },
         "max_chars": maxChars, "max_duration_ms": maxDuration]
    }
    var selectedExecution: [String: Any] {
        models.first { $0["id"] as? String == selectedModel }?["execution"] as? [String: Any] ?? [:]
    }
    var supportsGPU: Bool { (selectedExecution["devices"] as? [String] ?? ["cpu", "mps"]).contains("mps") }
    var supportsHotwords: Bool { selectedExecution["hotwords"] as? Bool ?? true }
    var submission: [String: Any] {
        ["paths": sources.map(\.path), "output_dir": outputDirectory, "recursive": recursive, "settings": options]
    }

    func perform(_ operation: String, _ arguments: [String: Any] = [:]) {
        guard pendingCommand == nil else { message = "先重送並確認前一次操作結果。"; return }
        Task {
            busy = true
            defer { busy = false }
            do {
                let command = try PendingCommand(operation, arguments: arguments)
                pendingCommand = command
                try await sendPending(command)
                if operation == "service.stop" {
                    serviceStopped = true
                    message = "背景服務正在停止；目前工作完成後結束"
                    return
                }
                if operation != "jobs.retry" { message = "操作已接受" }
                await refresh()
            } catch { message = error.localizedDescription }
        }
    }

    private func sendPending(_ command: PendingCommand) async throws {
        let data = try await Task.detached { try command.send() }.value
        let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        pendingCommand = nil
        guard envelope["success"] as? Bool == true else {
            let error = envelope["error"] as? [String: Any] ?? [:]
            throw NSError(domain: "ASRDesktop", code: 3, userInfo: [NSLocalizedDescriptionKey: error["message"] as? String ?? "操作失敗"])
        }
        if let result = envelope["result"] as? [String: Any], let retried = result["retried_count"] as? Int {
            message = "重試 \(retried) 筆，略過 \(result["skipped_count"] as? Int ?? 0) 筆（狀態不適用）。"
        }
        selectedIDs = []; allSelection = nil
    }

    func resendPending() {
        guard let command = pendingCommand else { return }
        Task {
            busy = true
            defer { busy = false }
            do {
                try await sendPending(command)
                message = "原請求已確認"
                await refresh()
            } catch { message = error.localizedDescription }
        }
    }

    func inspect() {
        Task {
            busy = true
            defer { busy = false }
            do {
                let result = try await call("intake.preview", submission) as? [String: Any]
                preview = result?["entries"] as? [[String: Any]] ?? []
                message = "可提交 \(result?["valid_count"] as? Int ?? 0) 個媒體檔案"
            } catch { message = error.localizedDescription }
        }
    }

    func submit() {
        Task {
            busy = true
            defer { busy = false }
            do {
                let result = try await call("submit", submission) as? [String: Any]
                message = "批次已接受：\(result?["accepted_count"] as? Int ?? 0) 個檔案。請按「恢復佇列」開始。"
                sources = []; preview = []
                await refresh()
            } catch { message = error.localizedDescription }
        }
    }

    func chooseSources() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = true; panel.allowsMultipleSelection = true
        if panel.runModal() == .OK { sources += panel.urls; preview = [] }
    }
    func chooseOutput() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true
        if panel.runModal() == .OK { outputDirectory = panel.url?.path ?? ""; preview = [] }
    }
}

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
    @StateObject private var model = DesktopModel()
    @ObservedObject var updates: ReleaseUpdates
    @State private var renameID: String?
    @State private var renameText = ""

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
                Text(model.paused ? "佇列已暫停" : "佇列運作中").foregroundStyle(.secondary)
                Button(model.paused ? "恢復佇列" : "暫停佇列") {
                    model.perform(model.paused ? "queue.resume" : "queue.pause")
                }
            }.padding()
            Divider()
            TabView {
                importView.tabItem { Label("匯入", systemImage: "square.and.arrow.down") }
                jobsView.tabItem { Label("任務", systemImage: "list.bullet.rectangle") }
                modelsView.tabItem { Label("模型", systemImage: "externaldrive") }
                settingsView.tabItem { Label("設定", systemImage: "gearshape") }
            }.padding(12)
            Divider()
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                Text(model.message.isEmpty ? "錄好的音訊／影片將在本機處理。" : model.message)
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
        .sheet(isPresented: Binding(get: { renameID != nil }, set: { if !$0 { renameID = nil } })) {
            VStack(alignment: .leading, spacing: 16) {
                Text("修改批次名稱").font(.headline)
                TextField("名稱", text: $renameText)
                Text("\(renameText.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.count) / 100 Unicode 字元")
                HStack {
                    Button("取消") { renameID = nil }
                    Button("儲存") { if let id = renameID { model.perform("batches.rename", ["id": id, "name": renameText]) }; renameID = nil }
                        .disabled(renameText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || renameText.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.count > 100)
                }
            }.padding(24).frame(width: 400)
        }
        .sheet(isPresented: Binding(get: { model.removal != nil }, set: { if !$0 { model.removal = nil } })) {
            VStack(alignment: .leading, spacing: 16) {
                Text("移除任務紀錄").font(.headline)
                Text("\(model.removal?["label"] as? String ?? "選取任務")：\(model.removal?["total"] as? Int ?? 0) 筆")
                Text("原始影音檔與已產生的 TXT、SRT、JSON 成果都會保留。移除後，無法從原任務查看詳情或重試。")
                Text("此操作不清理快取或釋放成果空間，且無法復原。")
                HStack {
                    Button("取消") { model.removal = nil }
                    Button("移除 \(model.removal?["total"] as? Int ?? 0) 筆紀錄", role: .destructive) {
                        if let value = model.removal {
                            model.perform("jobs.remove", ["selector": value["selector"] ?? [:], "target_token": value["target_token"] ?? ""])
                        }
                        model.removal = nil
                    }.disabled((model.removal?["total"] as? Int ?? 0) == 0)
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
        .task { await updates.check() }
        .task {
            await model.connect()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                if !Task.isCancelled { await model.refresh() }
            }
        }
    }

    private var importView: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("加入錄好的音訊與影片").font(.title2.bold())
            HStack {
                Button("選擇檔案或資料夾") { model.chooseSources() }
                Button("清除") { model.sources = []; model.preview = [] }
                Toggle("包含子資料夾", isOn: $model.recursive)
            }
            List {
                ForEach(model.sources, id: \.self) { url in
                    Label(url.path, systemImage: "doc")
                }
                if model.inspectionReading { Label("正在讀取各檔時長…", systemImage: "clock") }
                ForEach(Array(model.inspection.enumerated()), id: \.offset) { _, entry in
                    HStack {
                        Text(URL(fileURLWithPath: entry["source"] as? String ?? "").lastPathComponent)
                        Spacer()
                        Text(entry["error"] as? String ?? (entry["status"] as? String == "valid" ? MediaDuration.text(entry["duration_ms"] as? Double) : entry["status"] as? String ?? "時長未知"))
                    }
                }
                if model.sources.isEmpty { Text("也可以拖入檔案或資料夾").foregroundStyle(.secondary) }
            }
            .dropDestination(for: URL.self) { urls, _ in model.sources += urls; model.preview = []; return true }
            HStack {
                Button("選擇輸出資料夾") { model.chooseOutput() }
                Text(model.outputDirectory.isEmpty ? "尚未選擇" : model.outputDirectory).textSelection(.enabled)
            }
            outputOptions
            HStack {
                Button("預覽批次") { model.inspect() }
                Button("提交有效檔案") { model.submit() }.buttonStyle(.borderedProminent)
            }.disabled(model.sources.isEmpty || model.outputDirectory.isEmpty || model.busy)
            if !model.preview.isEmpty {
                List(Array(model.preview.enumerated()), id: \.offset) { _, entry in
                  VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(entry["source"] as? String ?? "")
                        Spacer()
                        Text(entry["status"] as? String == "valid" ? "可處理 · " + MediaDuration.text(entry["duration_ms"] as? Double) : entry["status"] as? String ?? "")
                    }
                    if let error = entry["error"] as? String { Text(error).foregroundStyle(.secondary) }
                    if let outputs = entry["outputs"] as? [String: String] {
                        ForEach(outputs.keys.sorted(), id: \.self) { format in
                            Text("\(format.uppercased())：\(outputs[format] ?? "")").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                  }
                }.frame(minHeight: 80, maxHeight: 160)
            }
        }.padding(12)
        .onChange(of: model.sources) { model.inspectSources() }
        .onChange(of: model.recursive) { model.inspectSources() }
        .onChange(of: model.includeTXT) { model.preview = [] }
        .onChange(of: model.includeSRT) { model.preview = [] }
        .onChange(of: model.includeJSON) { model.preview = [] }
    }

    private var outputOptions: some View {
        VStack(alignment: .leading, spacing: 8) {
          HStack {
            Picker("模型", selection: $model.selectedModel) {
                ForEach(Array(model.models.enumerated()), id: \.offset) { _, item in
                    Text(item["display_name"] as? String ?? item["id"] as? String ?? "模型")
                        .tag(item["id"] as? String ?? "")
                }
            }
            Picker("裝置", selection: $model.device) {
                Text("自動").tag("auto"); Text("CPU").tag("cpu")
                if model.supportsGPU { Text("GPU").tag("gpu") }
            }
            Picker("文字", selection: $model.script) {
                Text("台灣繁體").tag("traditional"); Text("簡體").tag("simplified"); Text("原文").tag("original")
            }
          }
          HStack {
            Toggle("TXT", isOn: $model.includeTXT)
            Toggle("SRT", isOn: $model.includeSRT)
            Toggle("JSON", isOn: $model.includeJSON)
          }
        }
        .onChange(of: model.selectedModel) {
            if !model.supportsGPU && ["gpu", "mps"].contains(model.device) { model.device = "auto" }
            if !model.supportsHotwords { model.hotwords = "" }
            model.preview = []
        }
    }

    private var jobsView: some View {
        HSplitView {
            VStack(alignment: .leading) {
                Text("批次").font(.headline)
                Button("全部任務") { model.batchID = "" }
                List {
                    ForEach(model.batches.compactMap { $0["id"] as? String }, id: \.self) { id in
                        if let batch = model.batches.first(where: { $0["id"] as? String == id }) {
                            Button { model.batchID = id } label: {
                                VStack(alignment: .leading) {
                                    Text(batch["name"] as? String ?? id).fontWeight(model.batchID == id ? .bold : .regular)
                                    Text("\(batch["total"] as? Int ?? 0) 筆 · \(Date(timeIntervalSince1970: batch["created"] as? Double ?? 0).formatted())").font(.caption)
                                }
                            }.buttonStyle(.plain)
                            .contextMenu {
                                Button("修改批次名稱") { renameText = batch["name"] as? String ?? ""; renameID = id }
                                Button("重試此批失敗任務") { model.perform("jobs.retry", ["selector": ["batch_id": id], "failed_only": true]) }
                                Button("移除此批全部任務紀錄", role: .destructive) { model.previewRemoval(["batch_id": id], label: batch["name"] as? String ?? id) }
                            }
                        }
                    }
                }
            }.frame(minWidth: 180, idealWidth: 220)
            VStack(alignment: .leading) {
                Text(model.scopeName).font(.headline)
                TextField("搜尋檔名或批次名稱", text: $model.query)
                Menu("狀態篩選（\(model.states.isEmpty ? "全部" : String(model.states.count))）") {
                    ForEach(["blocked", "queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"], id: \.self) { state in
                        Toggle(stateLabel(state), isOn: Binding(get: { model.states.contains(state) }, set: { if $0 { model.states.insert(state) } else { model.states.remove(state) } }))
                    }
                }
                Text("範圍共 \(model.counts.values.reduce(0, +)) 筆 · 符合 \(model.total) 筆").font(.caption)
                Text(model.counts.keys.sorted().map { "\(stateLabel($0)) \(model.counts[$0] ?? 0)" }.joined(separator: " · ")).font(.caption)
                HStack {
                    Button("全選符合結果") { model.selectAll() }
                    Button("清除選取") { model.selectedIDs = []; model.allSelection = nil }
                    Text("已選 \(model.selectedCount)")
                }
                HStack {
                    Button("重試選取") { model.retrySelection() }
                    Button("移除任務紀錄") { model.previewRemoval(model.currentSelection, label: "選取任務", token: model.allSelection?["target_token"] as? String) }
                }.disabled(model.selectedCount == 0 || model.busy)
                List {
                    ForEach(model.jobs.compactMap { $0["id"] as? String }, id: \.self) { id in
                        if let job = model.jobs.first(where: { $0["id"] as? String == id }) {
                            HStack {
                                Toggle("", isOn: Binding(get: { model.allSelection != nil || model.selectedIDs.contains(id) }, set: { checked in
                                    model.allSelection = nil
                                    if checked { model.selectedIDs.insert(id) } else { model.selectedIDs.remove(id) }
                                })).labelsHidden()
                                Button { model.showDetail(id) } label: {
                                    VStack(alignment: .leading) {
                                        Text(URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent)
                                        Text("\(stateLabel(job["state"] as? String ?? "")) · \(MediaDuration.text(job["duration_ms"] as? Double))").font(.caption)
                                    }
                                }.buttonStyle(.plain)
                            }.contextMenu {
                                Button("在 Finder 顯示原始檔") { model.reveal(job, outputs: false) }
                                Button("在 Finder 顯示成果") { model.reveal(job, outputs: true) }
                                Button("重試此任務") { model.perform("jobs.retry", ["selector": ["ids": [id]]]) }
                                Button("移除任務紀錄") { model.previewRemoval(["ids": [id]], label: "單筆任務") }
                            }
                        }
                    }
                    if model.jobs.isEmpty { Text(model.query.isEmpty && model.states.isEmpty ? "此範圍尚無任務" : "目前條件沒有符合的任務") }
                }
                HStack {
                    Button("上一頁") { model.changePage(max(0, model.offset - 100)) }.disabled(model.offset == 0)
                    Text("\(model.offset + (model.total == 0 ? 0 : 1))–\(model.offset + model.jobs.count)")
                    Button("下一頁") { model.changePage(model.offset + 100) }.disabled(model.offset + model.jobs.count >= model.total)
                }
            }.frame(minWidth: 300, idealWidth: 360)
            ScrollView {
                if let job = model.detail { jobDetail(job) }
                else { Text("選擇任務查看進度與結果").padding() }
            }.frame(minWidth: 300)
        }.disabled(!model.compatible)
    }

    private func jobDetail(_ job: [String: Any]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent).font(.title2.bold())
            Text(stateLabel(job["state"] as? String ?? ""))
            Text("媒體時長：" + MediaDuration.text(job["duration_ms"] as? Double))
            Text("批次：" + (model.batches.first { $0["id"] as? String == job["batch_id"] as? String }?["name"] as? String ?? ""))
            Text(job["source"] as? String ?? "").font(.callout).textSelection(.enabled)
            if let options = job["settings"] as? [String: Any] {
                Text("模型：\(options["model"] as? String ?? "") · 要求裝置：\(options["device"] as? String ?? "auto")")
            }
            Text("實際裝置：\(job["actual_device"] as? String ?? "尚未確定")")
            if let reason = job["device_reason"] as? String {
                Text(["insufficient_evidence": "自動：尚無合格比較證據，使用 CPU",
                      "incomplete_profile_identity": "環境資料不完整，保守使用 CPU",
                      "explicit_device": "依明確裝置設定執行",
                      "gpu_combination_quarantined": "此 GPU 組合需重新校準，目前使用 CPU",
                      "qualified_gpu_improvement": "合格比較顯示 GPU 至少快 10%",
                      "gpu_below_improvement_threshold": "GPU 比較未達升級門檻，使用 CPU",
                      "mps_compatibility_cpu_fallback": "GPU 相容性失敗，本次已改用 CPU"][reason] ?? "依本機裝置政策執行").foregroundStyle(.secondary)
            }
            if let progress = job["progress"] as? [String: Any] {
                Text(progress["message"] as? String ?? "處理中")
                if let current = progress["current"] as? Double, let total = progress["total"] as? Double, total > 0 {
                    ProgressView(value: current, total: total)
                    Text(progress["progress_kind"] as? String == "estimated" ? "估計進度" : "實際進度").font(.caption)
                } else { ProgressView().controlSize(.small) }
                if let elapsed = progress["elapsed_seconds"] as? Double { Text("階段已用 \(Int(elapsed)) 秒").font(.caption) }
                if let eta = progress["eta_seconds"] as? Double { Text("估計剩餘 \(Int(eta)) 秒").font(.caption) }
            }
            if let error = job["error"] as? [String: Any] { Text(error["message"] as? String ?? "處理失敗").foregroundStyle(.red).textSelection(.enabled) }
            HStack {
                Button("取消") { model.perform("jobs.cancel", ["id": job["id"] ?? ""]) }
                Button("重試") { model.perform("jobs.retry", ["selector": ["ids": [job["id"] ?? ""]]]) }
                Button("移除任務紀錄") { model.previewRemoval(["ids": [job["id"] ?? ""]], label: "單筆任務") }
            }
            HStack {
                Button("在 Finder 顯示原始檔") { model.reveal(job, outputs: false) }
                Button("在 Finder 顯示成果") { model.reveal(job, outputs: true) }
            }
            Text("已交付：" + ((job["delivered_outputs"] as? [String: String] ?? [:]).keys.sorted().joined(separator: "、")))
            Text("尚未交付：" + ((job["undelivered_outputs"] as? [String] ?? []).joined(separator: "、")))
            Text("已遺失：" + ((job["missing_outputs"] as? [String] ?? []).joined(separator: "、")))
            if let outputs = job["outputs"] as? [String: String] {
                ForEach(outputs.keys.sorted(), id: \.self) { format in
                    Text("\(format.uppercased())：\(outputs[format] ?? "")").font(.caption).textSelection(.enabled)
                }
            }
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
    }

    private var modelsView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("安裝後下載模型").font(.title2.bold())
                Text("模型全部驗證完成後才會就緒；下載完成後可離線使用。")
                ForEach(Array(model.models.enumerated()), id: \.offset) { _, item in
                    GroupBox(item["display_name"] as? String ?? item["id"] as? String ?? "模型") {
                        VStack(alignment: .leading, spacing: 10) {
                            if let requirements = item["requirements"] as? [String: String] {
                                Text("電腦需求").font(.headline)
                                ForEach(["platform", "cpu", "gpu", "minimum_memory", "recommended_memory", "notes"], id: \.self) { key in
                                    if let value = requirements[key] { Text(value).font(.callout).textSelection(.enabled) }
                                }
                                if let source = requirements["source"], let url = URL(string: source) {
                                    Link("模型文件／需求依據", destination: url).font(.caption)
                                }
                            }
                            Text("下載量：\(ByteCountFormatter.string(fromByteCount: Int64(item["download_bytes"] as? Int ?? 0), countStyle: .file))")
                            Text("準備所需可用空間：\(ByteCountFormatter.string(fromByteCount: Int64(item["required_free_bytes"] as? Int ?? 0), countStyle: .file))")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("目前使用：\(ByteCountFormatter.string(fromByteCount: Int64(item["storage_bytes"] as? Int ?? 0), countStyle: .file))")
                                .font(.caption).foregroundStyle(.secondary)
                            Text(stateLabel(item["state"] as? String ?? "missing"))
                            if let current = item["downloaded_bytes"] as? Double, let total = item["total_bytes"] as? Double, total > 0 {
                                ProgressView(value: min(current, total), total: total)
                            }
                            if let error = item["error"] as? [String: Any] { Text(error["message"] as? String ?? "下載失敗").foregroundStyle(.red) }
                            HStack {
                                Button("下載／修復") { model.perform("models.download", ["id": item["id"] ?? ""]) }
                                Button("重新驗證") { model.perform("models.verify", ["id": item["id"] ?? ""]) }
                                Button("移除") { model.perform("models.remove", ["id": item["id"] ?? ""]) }
                            }
                        }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }.padding(20)
        }
    }

    private var settingsView: some View {
      ScrollView {
        VStack(alignment: .leading, spacing: 20) {
            UpdateSettingsView(updates: updates)
            Text("新任務的預設值").font(.title2.bold())
            Text(model.defaultsSummary).font(.callout).foregroundStyle(.secondary)
            outputOptions
            TextField("辨識語言", text: $model.language)
            TextField("熱詞（逗號分隔）", text: $model.hotwords)
                .disabled(!model.supportsHotwords)
            if !model.supportsHotwords { Text("此模型未提供熱詞設定").font(.caption).foregroundStyle(.secondary) }
            Stepper("字幕每行最多 \(model.maxChars) 單位", value: $model.maxChars, in: 1...100)
            Stepper("字幕最長 \(Double(model.maxDuration) / 1000, specifier: "%.2f") 秒", value: $model.maxDuration, in: 250...30000, step: 250)
            Text("TXT 與 SRT 預設同時輸出；JSON 保留原始辨識文字。變更只影響新提交的任務。")
                .foregroundStyle(.secondary)
            Toggle("明確允許覆寫既有輸出", isOn: $model.overwrite)
            Button("儲存預設值") { model.perform("settings.set", ["settings": model.options]) }
            Button("選擇樣本並校準 CPU／GPU") {
                let panel = NSOpenPanel()
                panel.canChooseFiles = true; panel.canChooseDirectories = false
                if panel.runModal() == .OK, let url = panel.url {
                    model.perform("device.calibrate", ["paths": [url.path], "settings": ["model": model.selectedModel]])
                }
            }
            Text("校準使用同一個佇列，依序測試 CPU 與 GPU；沒有合格品質與資源證據時，自動仍使用 CPU。")
                .font(.callout).foregroundStyle(.secondary)
            Divider()
            Text("關閉視窗後，已接受的工作仍會繼續。停止服務會先暫停領取，再等目前工作完成。")
            HStack {
                Button("啟動／重新連線") { Task { await model.connect() } }
                Button("停止背景服務") { model.perform("service.stop") }
                Button("診斷安裝") {
                    Task {
                        model.busy = true
                        defer { model.busy = false }
                        do {
                            let result = try await Task.detached { try RuntimeDiagnostics.run() }.value
                            model.message = result.status == 0 ? "內建 runtime、FunASR 與媒體工具實際診斷通過" : "內建環境無法完整執行，請重新安裝完整且相符版本的 App。"
                        } catch { model.message = "無法啟動內建環境，請重新安裝完整 App：" + error.localizedDescription }
                    }
                }
                Button("安裝 CLI 連結") {
                    do { model.message = "已建立 \(try CommandLink.install().path)；請自行確認 ~/.local/bin 已在 PATH。" }
                    catch { model.message = error.localizedDescription }
                }
            }
        }.padding(24)
      }
    }

    private func stateLabel(_ state: String) -> String {
        ["queued": "等待執行", "blocked": "等待指定模型", "running": "處理中", "completed": "完成", "failed": "失敗",
         "cancelled": "已取消", "cancelling": "正在取消", "interrupted": "已中斷，需明確重試", "ready": "已就緒",
         "missing": "尚未下載", "downloading": "下載中", "verifying": "驗證中"][state] ?? state
    }
}
