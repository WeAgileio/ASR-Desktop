import AppKit
import ASRDesktopCore
import SwiftUI

@MainActor
final class DesktopModel: ObservableObject {
    @Published var jobs: [[String: Any]] = []
    @Published var models: [[String: Any]] = []
    @Published var paused = true
    @Published var pane: WorkspacePane = .intake
    @Published var connection: ServiceConnection = .connecting
    @Published var connectionError = ""
    @Published var feedback: [WorkspacePane: OperationFeedback] = [:]
    @Published var acceptedBatchID: String?
    @Published var detailStopped = false
    @Published var showingDetail = false
    var commandRequest: (@MainActor (PendingCommand) async throws -> Data)?
    var mutationBlocked: Bool { busy || pendingCommand != nil || connection != .ready }
    var queueLabel: String { connection == .ready ? (paused ? "佇列已暫停" : "佇列運作中") : "佇列狀態待確認" }

    func report(_ pane: WorkspacePane, _ title: String, _ value: String, _ kind: OperationFeedback.Kind = .failure) {
        feedback[pane] = OperationFeedback(title: title, message: value, kind: kind)
    }

    func viewAcceptedBatch() {
        guard let acceptedBatchID else { return }
        batchID = acceptedBatchID; query = ""; states = []; pane = .jobs
    }

    @Published var sources: [URL] = [] { didSet { invalidatePreview(); invalidateInspection() } }
    @Published var outputDirectory = "" { didSet { invalidatePreview() } }
    @Published var recursive = false { didSet { invalidatePreview(); invalidateInspection() } }
    @Published var importDraft = RecognitionOptions() { didSet { invalidatePreview() } }
    @Published var settingsDraft = RecognitionOptions()
    @Published private(set) var savedDefaults: RecognitionOptions?
    @Published var defaultsChanged = false
    @Published var previewInput: Data?
    @Published var previewReading = false
    private var previewGeneration = 0
    private var importInitialized = false
    var request: (@MainActor (String, [String: Any]) async throws -> Any)?
    @Published var offset = 0
    @Published var total = 0
    @Published var counts: [String: Int] = [:]
    @Published var defaultsSummary = ""
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

    func connect() async {
        connection = .connecting; connectionError = ""
        do {
            if request == nil { try await Task.detached { try ServiceClient.ensureReady() }.value }
            serviceStopped = false
            let status = try await call("service.status") as? [String: Any] ?? [:]
            compatible = TaskCapabilities.supports(status["capabilities"] as? [String] ?? [])
            guard compatible else { connection = .incompatible; connectionError = "背景服務缺少任務管理能力，請使用相同版本 App 並重新啟動服務。"; return }
            await refresh()
        } catch { connection = .unavailable; connectionError = error.localizedDescription }
    }

    func call(_ operation: String, _ arguments: [String: Any] = [:]) async throws -> Any {
        if let request { return try await request(operation, arguments) }
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
        offset = 0; selectedIDs = []; allSelection = nil; detail = nil; showingDetail = false; detailStopped = false
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
                    if queryState.accepts(generation) && detailVersion == detailGeneration {
                        detail = value
                        await checkDetailStopped(id, version: detailVersion)
                    }
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
                    if queryState.accepts(generation) { allSelection = nil; report(.jobs, "選取已變更", "請重新選取及確認。") }
                }
            }
            models = try await call("models.list") as? [[String: Any]] ?? []
            if let defaults = try await call("settings.show") as? [String: Any] { syncDefaults(defaults) }
            connection = .ready; connectionError = ""
        } catch { connection = .unavailable; connectionError = error.localizedDescription }
        let again = queryState.finish()
        if again { await refresh() }
    }

    func showDetail(_ id: String) {
        showingDetail = true; detailStopped = false; detail = nil
        detailGeneration += 1
        let generation = detailGeneration
        Task {
            do {
                let value = try await call("jobs.show", ["id": id]) as? [String: Any]
                if generation == detailGeneration { detail = value; await checkDetailStopped(id, version: generation) }
            } catch { if generation == detailGeneration { detail = nil; report(.jobs, "讀取任務失敗", error.localizedDescription) } }
        }
    }
    func checkDetailStopped(_ id: String, version: Int) async {
        do {
            let result = try await call("jobs.selection.preview", ["selector": ["ids": [id]]]) as? [String: Any] ?? [:]
            if version == detailGeneration {
                detailStopped = (result["cannot_remove"] as? [[String: Any]])?.isEmpty == true
            }
        } catch { if version == detailGeneration { detailStopped = false } }
    }

    func returnToList() { showingDetail = false }

    func clearFilters() { query = ""; states = [] }

    func setSelected(_ id: String, checked: Bool) {
        if allSelection != nil {
            allSelection = nil; selectedIDs = []
            report(.jobs, "選取範圍已變更", "已離開全選符合結果，改為個別勾選。", .success)
        }
        if checked { selectedIDs.insert(id) } else { selectedIDs.remove(id) }
    }

    func selectAll() {
        let captured = selector
        Task {
            do {
                let result = try await call("jobs.selection.preview", ["selector": captured]) as? [String: Any]
                if NSDictionary(dictionary: captured).isEqual(to: selector) { allSelection = result; selectedIDs = [] }
            } catch { report(.jobs, "無法全選", error.localizedDescription) }
        }
    }
    func retrySelection() {
        var arguments: [String: Any] = ["selector": currentSelection]
        if let token = allSelection?["target_token"] { arguments["target_token"] = token }
        perform("jobs.retry", arguments)
    }

    func retryJob(_ id: String) {
        guard !mutationBlocked else { return }
        Task {
            do {
                let selector: [String: Any] = ["ids": [id]]
                let result = try await call("jobs.selection.preview", ["selector": selector]) as? [String: Any] ?? [:]
                guard (result["cannot_remove"] as? [[String: Any]])?.isEmpty == true else {
                    report(.jobs, "尚不能重試", "請先等待任務停止及執行回收，再重試。")
                    return
                }
                perform("jobs.retry", ["selector": selector, "target_token": result["target_token"] ?? ""])
            } catch { report(.jobs, "無法重試", error.localizedDescription) }
        }
    }
    func previewRemoval(_ selector: [String: Any], label: String, token: String? = nil) {
        Task {
            do {
                var args: [String: Any] = ["selector": selector]
                if let token { args["target_token"] = token }
                var value = try await call("jobs.selection.preview", args) as? [String: Any] ?? [:]
                if !(value["cannot_remove"] as? [[String: Any]] ?? []).isEmpty {
                    report(.jobs, "無法移除", "有任務仍執行、取消中或尚未回收；請先停止並等待，再重新確認。"); return
                }
                value["label"] = label; removal = value
            } catch { report(.jobs, "無法確認移除", error.localizedDescription); allSelection = nil }
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
            } catch { report(.jobs, "Finder 定位失敗", error.localizedDescription) }
        }
    }

    private func invalidateInspection() {
        inspectionGeneration += 1
        inspectionTask?.cancel()
        inspection = []; inspectionReading = false
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
            } catch { if generation == inspectionGeneration && !Task.isCancelled { report(.intake, "來源讀取失敗", error.localizedDescription) } }
        }
    }

    var settingsDirty: Bool { settingsDraft != (savedDefaults ?? RecognitionOptions()) }

    func syncDefaults(_ values: [String: Any]) {
        let updated = RecognitionOptions(values)
        let clean = !settingsDirty
        let first = savedDefaults == nil
        let changed = savedDefaults != updated
        savedDefaults = updated
        defaultsSummary = "已儲存：\(updated.model) · \(updated.device) · \(updated.script)"
        if clean { settingsDraft = updated; defaultsChanged = false }
        else if changed { defaultsChanged = true }
        if first && !importInitialized && sources.isEmpty && importDraft == RecognitionOptions() {
            importDraft = updated
            importInitialized = true
        }
    }

    func reloadSettings() {
        guard let savedDefaults else { return }
        settingsDraft = savedDefaults; defaultsChanged = false
    }

    func applyDefaults() {
        guard let savedDefaults else { return }
        importDraft = savedDefaults; importInitialized = true
    }

    var options: [String: Any] { importDraft.dictionary }
    var submissionInput: Data? { try? JSONSerialization.data(withJSONObject: submission, options: [.sortedKeys]) }
    var validPreviewCount: Int { preview.filter { $0["status"] as? String == "valid" }.count }
    var previewCurrent: Bool { previewInput != nil && previewInput == submissionInput }
    var submissionReason: String? {
        if sources.isEmpty { return "請先加入音訊、影片或資料夾。" }
        if outputDirectory.isEmpty { return "請選擇輸出資料夾。" }
        if importDraft.formats.isEmpty { return "請至少選擇一種輸出格式。" }
        if previewReading { return "正在驗證目前輸入，請稍候。" }
        if !previewCurrent { return "請先預覽目前的來源、輸出與設定。" }
        if validPreviewCount == 0 { return "預覽沒有可提交的有效檔案，請修正來源。" }
        return nil
    }
    func invalidatePreview() {
        previewGeneration += 1; previewInput = nil; preview = []; previewReading = false
    }

    var submission: [String: Any] {
        ["paths": sources.map(\.path), "output_dir": outputDirectory, "recursive": recursive, "settings": options]
    }

    func operationTitle(_ operation: String) -> String {
        ["submit": "提交批次", "settings.set": "儲存預設值", "models.download": "準備模型",
         "models.verify": "驗證模型", "models.remove": "移除模型", "jobs.cancel": "取消任務",
         "jobs.retry": "重試任務", "jobs.remove": "移除任務紀錄", "batches.rename": "修改批次名稱",
         "queue.pause": "暫停佇列", "queue.resume": "恢復佇列", "device.calibrate": "校準裝置",
         "service.stop": "停止背景服務"][operation] ?? "操作結果"
    }

    func operationPane(_ operation: String) -> WorkspacePane {
        if operation == "submit" { return .intake }
        if operation.hasPrefix("models.") { return .models }
        if operation.hasPrefix("jobs.") || operation.hasPrefix("batches.") || operation.hasPrefix("queue.") { return .jobs }
        return .settings
    }

    func perform(_ operation: String, _ arguments: [String: Any] = [:]) {
        guard !mutationBlocked else { return }
        busy = true
        Task { await execute(operation, arguments) }
    }

    func execute(_ operation: String, _ arguments: [String: Any] = [:]) async {
        guard pendingCommand == nil else { return }
        busy = true
        defer { busy = false }
        let area = operationPane(operation)
        report(area, operationTitle(operation), "正在送出，請稍候。", .working)
        do {
            let command = try PendingCommand(operation, arguments: arguments)
            pendingCommand = command
            try await finishCommand(command)
        } catch {
            report(area, operationTitle(operation), error.localizedDescription + (pendingCommand == nil ? "" : "；結果尚未確認，請重送原請求。"), pendingCommand == nil ? .failure : .uncertain)
        }
    }

    private func finishCommand(_ command: PendingCommand) async throws {
        let data: Data
        if let commandRequest { data = try await commandRequest(command) }
        else { data = try await Task.detached { try command.send() }.value }
        guard let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let success = envelope["success"] as? Bool else { throw ControlSocket.ControlError.invalidResponse }
        pendingCommand = nil
        guard success else {
            let error = envelope["error"] as? [String: Any] ?? [:]
            throw NSError(domain: "ASRDesktop", code: 3, userInfo: [NSLocalizedDescriptionKey: error["message"] as? String ?? "操作失敗，請修正後再試。"])
        }
        let result = envelope["result"] as? [String: Any] ?? [:]
        let area = operationPane(command.operation)
        if command.operation == "settings.set" { syncDefaults(result); if !settingsDirty { defaultsChanged = false } }
        if command.operation == "submit" {
            acceptedBatchID = result["id"] as? String
            sources = []; inspection = []
            if let savedDefaults { importDraft = savedDefaults }
        }
        if command.operation.hasPrefix("jobs.") { selectedIDs = []; allSelection = nil }
        if command.operation == "service.stop" {
            serviceStopped = true; connection = .stopping
            report(area, "停止背景服務", "已接受；目前工作完成後結束。", .success)
            return
        }
        await refresh()
        if command.operation == "submit" {
            let state = connection == .ready ? (paused ? "佇列已暫停；請明確恢復佇列。" : "已加入運作中的佇列；請查看任務狀態。") : "已接受，佇列狀態待確認；請重新連線。"
            report(area, "批次已接受", "\(result["accepted_count"] as? Int ?? 0) 個檔案。" + state + " 缺少指定模型的任務會等待模型準備。", .success)
        } else if let retried = result["retried_count"] as? Int {
            report(area, "重試結果", "重試 \(retried) 筆，略過 \(result["skipped_count"] as? Int ?? 0) 筆（狀態不適用）。", .success)
        } else {
            report(area, operationTitle(command.operation), "操作已接受。", .success)
        }
    }

    func resendPending() {
        guard !busy, pendingCommand != nil else { return }
        busy = true
        Task { await confirmPending() }
    }

    func confirmPending() async {
        guard let command = pendingCommand else { busy = false; return }
        busy = true
        defer { busy = false }
        do { try await finishCommand(command) }
        catch { report(operationPane(command.operation), operationTitle(command.operation), error.localizedDescription + (pendingCommand == nil ? "" : "；請重送原請求以確認結果。"), pendingCommand == nil ? .failure : .uncertain) }
    }

    func inspect() {
        Task { await previewBatch() }
    }

    func previewBatch() async {
        guard !sources.isEmpty && !outputDirectory.isEmpty && !importDraft.formats.isEmpty else { return }
        invalidatePreview()
        let generation = previewGeneration
        let input = submissionInput
        let arguments = submission
        previewReading = true
        defer { if generation == previewGeneration { previewReading = false } }
        do {
            let result = try await call("intake.preview", arguments) as? [String: Any] ?? [:]
            guard generation == previewGeneration && input == submissionInput else { return }
            preview = result["entries"] as? [[String: Any]] ?? []
            previewInput = input
            report(.intake, "預覽完成", "可提交 \(validPreviewCount) 個媒體檔案。", .success)
        } catch { if generation == previewGeneration { report(.intake, "預覽失敗", error.localizedDescription) } }
    }

    func submit() {
        guard submissionReason == nil else { report(.intake, "尚不能提交", submissionReason ?? ""); return }
        perform("submit", submission)
    }

    func chooseSources() {
        guard !busy && pendingCommand == nil else { return }
        pane = .intake
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
