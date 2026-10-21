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
    private var refreshing = false
    private var savedDefaults: [String: Any] = [:]

    func connect() async {
        do {
            try await Task.detached { try ServiceClient.ensureReady() }.value
            serviceStopped = false
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
            throw NSError(domain: "ASRDesktop", code: 3, userInfo: [NSLocalizedDescriptionKey: error?["message"] as? String ?? "操作失敗，請檢查背景服務與模型狀態。"])
        }
        return envelope["result"] ?? [:]
    }

    func refresh() async {
        guard !serviceStopped && !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let page = try await call("jobs.list", ["offset": offset, "limit": 100]) as? [String: Any] ?? [:]
            jobs = page["jobs"] as? [[String: Any]] ?? []
            paused = page["queue_paused"] as? Bool ?? true
            total = page["total"] as? Int ?? jobs.count
            counts = page["counts"] as? [String: Int] ?? [:]
            models = try await call("models.list") as? [[String: Any]] ?? []
            if let defaults = try await call("settings.show") as? [String: Any] { syncDefaults(defaults) }
        } catch { message = error.localizedDescription }
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
        Task {
            busy = true
            defer { busy = false }
            do {
                _ = try await call(operation, arguments)
                if operation == "service.stop" {
                    serviceStopped = true
                    message = "背景服務正在停止；目前工作完成後結束"
                    return
                }
                message = "操作已接受"
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
    @State private var selectedJob: String?

    var body: some View {
        VStack(spacing: 0) {
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
                Link("karakuri.tech", destination: URL(string: "https://karakuri.tech")!)
                    .focusable()
                    .font(.callout)
                    .fixedSize()
                    .layoutPriority(1)
                    .accessibilityLabel("karakuri.tech")
                    .accessibilityHint("以預設瀏覽器開啟來源網站")
            }.padding(12)
        }
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
                ForEach(Array(model.sources.enumerated()), id: \.offset) { _, url in
                    Label(url.path, systemImage: "doc")
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
                        Text(entry["status"] as? String == "valid" ? "可處理" : entry["status"] as? String ?? "")
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
        .onChange(of: model.recursive) { model.preview = [] }
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
      VStack {
        HStack {
            Text("共 \(model.total) 檔 · 完成 \(model.counts["completed", default: 0]) · 失敗 \(model.counts["failed", default: 0]) · 取消 \(model.counts["cancelled", default: 0])")
            Spacer()
            Button("上一頁") { model.offset = max(0, model.offset - 100); Task { await model.refresh() } }.disabled(model.offset == 0)
            Text("\(model.offset + (model.total == 0 ? 0 : 1))–\(model.offset + model.jobs.count)")
            Button("下一頁") { model.offset += 100; Task { await model.refresh() } }.disabled(model.offset + model.jobs.count >= model.total)
        }.padding(8)
        HSplitView {
            List(selection: $selectedJob) {
                ForEach(Array(model.jobs.enumerated()), id: \.offset) { _, job in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent)
                        Text(stateLabel(job["state"] as? String ?? "")).font(.caption).foregroundStyle(.secondary)
                    }.tag(job["id"] as? String ?? "")
                }
            }.frame(minWidth: 240)
            ScrollView {
                if let job = model.jobs.first(where: { $0["id"] as? String == selectedJob }) {
                    jobDetail(job)
                } else { Text("選擇任務查看進度與結果").foregroundStyle(.secondary).padding(32) }
            }.frame(minWidth: 340, maxWidth: .infinity)
        }
      }
    }

    private func jobDetail(_ job: [String: Any]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(URL(fileURLWithPath: job["source"] as? String ?? "").lastPathComponent).font(.title2.bold())
            Text(stateLabel(job["state"] as? String ?? ""))
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
                Button("重試") { model.perform("jobs.retry", ["id": job["id"] ?? ""]) }
                Menu("整批操作") {
                    Button("取消整批") { model.perform("jobs.cancel", ["id": job["batch_id"] ?? ""]) }
                    Button("重試整批") { model.perform("jobs.retry", ["id": job["batch_id"] ?? ""]) }
                }
                Button("開啟輸出資料夾") { NSWorkspace.shared.open(URL(fileURLWithPath: job["output_dir"] as? String ?? "")) }
            }
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
