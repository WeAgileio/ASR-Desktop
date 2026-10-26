import Foundation
import Testing
import ASRDesktopCore
@testable import ASRDesktopApp

@Test @MainActor func draftsStayIndependentAcrossExternalUpdates() {
    let model = DesktopModel()
    model.syncDefaults(["model": "first"])
    #expect(model.importDraft.model == "first")
    model.importDraft.model = "import"
    model.settingsDraft.model = "unsaved"
    model.syncDefaults(["model": "external"])
    #expect(model.importDraft.model == "import")
    #expect(model.settingsDraft.model == "unsaved")
    #expect(model.defaultsChanged)
    model.reloadSettings()
    #expect(model.settingsDraft.model == "external")
    model.settingsDraft.model = "saved"
    model.syncDefaults(model.settingsDraft.dictionary)
    #expect(!model.settingsDirty)
    #expect(model.importDraft.model == "import")
    model.applyDefaults()
    #expect(model.importDraft.model == "saved")
}

@Test @MainActor func firstLoadDoesNotOverwriteAnEditedDraft() {
    let model = DesktopModel()
    model.importDraft.model = "edited"
    model.settingsDraft.language = "English"
    model.syncDefaults(["model": "external"])
    #expect(model.importDraft.model == "edited")
    #expect(model.settingsDraft.language == "English")
}

@MainActor private func previewModel() -> DesktopModel {
    let model = DesktopModel()
    model.sources = [URL(fileURLWithPath: "/tmp/input.wav")]
    model.outputDirectory = "/tmp/output"
    model.request = { operation, _ in
        #expect(operation == "intake.preview")
        return ["entries": [["source": "/tmp/input.wav", "status": "valid", "duration_ms": 1200.0]]]
    }
    return model
}

@Test @MainActor func allSubmissionInputsInvalidatePreview() async {
    let edits: [(DesktopModel) -> Void] = [
        { $0.sources.append(URL(fileURLWithPath: "/tmp/other.wav")) },
        { $0.outputDirectory = "/tmp/other" }, { $0.recursive.toggle() },
        { $0.importDraft.model = "paraformer" }, { $0.importDraft.device = "cpu" },
        { $0.importDraft.script = "original" }, { $0.importDraft.includeTXT.toggle() },
        { $0.importDraft.includeSRT.toggle() }, { $0.importDraft.includeJSON.toggle() },
        { $0.importDraft.language = "English" }, { $0.importDraft.hotwords = "test" },
        { $0.importDraft.maxChars += 1 }, { $0.importDraft.maxDuration += 250 },
        { $0.importDraft.overwrite.toggle() }
    ]
    for edit in edits {
        let model = previewModel()
        await model.previewBatch()
        #expect(model.submissionReason == nil)
        edit(model)
        #expect(!model.previewCurrent)
        #expect(model.submissionReason != nil)
    }
}

@Test @MainActor func latePreviewCannotEnableSubmission() async {
    let model = previewModel()
    model.request = { _, _ in
        model.importDraft.device = "cpu"
        return ["entries": [["status": "valid"]]]
    }
    await model.previewBatch()
    #expect(model.preview.isEmpty)
    #expect(!model.previewCurrent)
    #expect(!model.previewReading)
    #expect(model.submissionReason != nil)
}

@Test @MainActor func clearingSourcesRejectsLateInspectionBeforeViewUpdates() async {
    let model = DesktopModel()
    model.sources = [URL(fileURLWithPath: "/tmp/input.wav")]
    var called = false
    model.request = { _, _ in
        called = true
        model.sources = []
        return ["id": "old-inspection", "state": "complete", "entries": [["source": "/tmp/input.wav", "status": "valid"]]]
    }
    model.inspectSources()
    for _ in 0..<20 where !called { await Task.yield() }
    #expect(called)
    #expect(model.sources.isEmpty && model.inspection.isEmpty)
    #expect(!model.inspectionReading)
}

@Test @MainActor func invalidPreviewAndFormatsDoNotSubmit() async {
    let model = previewModel()
    model.request = { _, _ in ["entries": [["status": "invalid", "error": "No audio"]]] }
    await model.previewBatch()
    #expect(model.previewCurrent)
    #expect(model.validPreviewCount == 0)
    #expect(model.submissionReason != nil)
    model.importDraft.includeTXT = false; model.importDraft.includeSRT = false
    #expect(model.submissionReason == "請至少選擇一種輸出格式。")
    model.submit()
    #expect(!model.busy)
}

@MainActor private func connectedModel(paused: Bool = true, failsRefresh: Bool = false) -> DesktopModel {
    let model = DesktopModel()
    model.compatible = true; model.connection = .ready
    model.request = { operation, _ in
        switch operation {
        case "jobs.list":
            if failsRefresh { throw URLError(.notConnectedToInternet) }
            return ["jobs": [], "total": 0, "scope_counts": [:], "queue_paused": paused] as [String: Any]
        case "batches.list": return ["batches": [], "total": 0]
        case "models.list": return [["id": "fun-asr-nano", "state": "missing"]]
        case "settings.show": return RecognitionOptions().dictionary
        default: throw URLError(.badServerResponse)
        }
    }
    return model
}

@Test @MainActor func serviceFailureDoesNotOverwriteOperationFeedback() async {
    let model = connectedModel(failsRefresh: true)
    model.report(.intake, "輸出權限不足", String(repeating: "請修正權限。", count: 60))
    let original = model.feedback[.intake]
    model.sources = [URL(fileURLWithPath: "/tmp/draft.wav")]
    await model.refresh()
    #expect(model.connection == .unavailable)
    #expect(model.queueLabel == "佇列狀態待確認")
    #expect(model.feedback[.intake] == original)
    #expect(model.sources.count == 1)

    let initial = DesktopModel()
    initial.request = { _, _ in throw URLError(.cannotConnectToHost) }
    await initial.connect()
    #expect(initial.connection == .unavailable)
    #expect(initial.queueLabel == "佇列狀態待確認")
    initial.request = { _, _ in ["capabilities": []] }
    await initial.connect()
    #expect(initial.connection == .incompatible)
}

@Test @MainActor func acceptedBatchUsesConfirmedQueueState() async throws {
    for paused in [false, true] {
        let model = connectedModel(paused: paused)
        var sent: [String] = []
        model.commandRequest = { command in
            sent.append(command.operation)
            return try JSONSerialization.data(withJSONObject: ["success": true, "result": ["id": "batch-test", "accepted_count": 2]])
        }
        model.sources = [URL(fileURLWithPath: "/tmp/input.wav")]
        await model.execute("submit", model.submission)
        #expect(model.acceptedBatchID == "batch-test")
        #expect(model.sources.isEmpty)
        #expect(sent == ["submit"])
        let text = model.feedback[.intake]?.message ?? ""
        #expect(text.contains(paused ? "請明確恢復佇列" : "運作中的佇列"))
        if !paused { #expect(!text.contains("請明確恢復佇列")) }
        model.viewAcceptedBatch()
        #expect(model.pane == .jobs && model.batchID == "batch-test")
    }
    let model = connectedModel(failsRefresh: true)
    model.commandRequest = { _ in try JSONSerialization.data(withJSONObject: ["success": true, "result": ["id": "batch-test", "accepted_count": 1]]) }
    await model.execute("submit", model.submission)
    #expect(model.feedback[.intake]?.message.contains("狀態待確認") == true)
    #expect(model.acceptedBatchID == "batch-test")
}

@Test @MainActor func lostResponseReplaysExactSubmissionAndKeepsDraft() async throws {
    let model = connectedModel()
    model.sources = [URL(fileURLWithPath: "/tmp/draft.wav")]
    var commands: [PendingCommand] = []
    model.commandRequest = { command in
        commands.append(command)
        if commands.count == 1 { throw URLError(.timedOut) }
        return try JSONSerialization.data(withJSONObject: ["success": true, "result": ["id": "batch-replayed", "accepted_count": 1]])
    }
    await model.execute("submit", model.submission)
    #expect(model.sources.count == 1)
    #expect(model.pendingCommand != nil && model.mutationBlocked)
    #expect(model.feedback[.intake]?.kind == .uncertain)
    await model.execute("queue.resume")
    #expect(commands.count == 1)
    await model.confirmPending()
    #expect(commands.count == 2)
    #expect(commands[0].requestID == commands[1].requestID)
    #expect(commands[0].arguments == commands[1].arguments)
    #expect(model.pendingCommand == nil && model.sources.isEmpty)
    #expect(model.acceptedBatchID == "batch-replayed")
}

@Test @MainActor func rejectedSubmissionRetainsEditableDraft() async throws {
    let model = connectedModel()
    model.sources = [URL(fileURLWithPath: "/tmp/draft.wav")]
    model.commandRequest = { _ in try JSONSerialization.data(withJSONObject: ["success": false, "error": ["message": "Source changed"]]) }
    await model.execute("submit", model.submission)
    #expect(model.sources.count == 1)
    #expect(model.pendingCommand == nil && !model.busy)
    #expect(model.feedback[.intake]?.kind == .failure)
    #expect(model.acceptedBatchID == nil)
}

@Test func jobActionsAndProgressStayTruthful() {
    for state in ["queued", "blocked", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"] {
        let job: [String: Any] = ["state": state]
        #expect(JobPresentation.canCancel(job) == ["queued", "blocked", "running"].contains(state))
        #expect(JobPresentation.canRetry(job, stopped: true) == ["failed", "cancelled", "interrupted"].contains(state))
        #expect(!JobPresentation.canRetry(job, stopped: false))
        #expect(JobPresentation.canRemove(job, stopped: true) == !["running", "cancelling"].contains(state))
        #expect(!JobPresentation.canRemove(job, stopped: false))
    }
    #expect(JobPresentation.fraction(["progress_kind": "actual", "current": 2.0, "total": 4.0]) == 0.5)
    #expect(JobPresentation.fraction(["progress_kind": "estimated", "current": 2.0, "total": 4.0]) == 0.5)
    #expect(JobPresentation.fraction([:]) == nil)
    #expect(JobPresentation.fraction(["progress_kind": "indeterminate", "current": 2.0, "total": 4.0]) == nil)
    #expect(JobPresentation.fraction(["progress_kind": "actual", "current": Double.nan, "total": 4.0]) == nil)
    #expect(JobPresentation.fraction(["progress_kind": "actual", "current": 5.0, "total": 4.0]) == nil)
    #expect(JobPresentation.fraction(["progress_kind": "actual", "current": 0.0, "total": 0.0]) == nil)
    #expect(!JobPresentation.hasOutputs(["outputs": ["txt": "/tmp/planned.txt"]]))
    #expect(JobPresentation.hasOutputs(["delivered_outputs": ["txt": "/tmp/actual.txt"], "missing_outputs": ["srt"]]))
}

@Test @MainActor func cleanupMustBeConfirmedBeforeSingleRetry() async {
    let model = connectedModel()
    model.request = { _, _ in ["cannot_remove": [["id": "job-a", "reason": "worker_not_reaped"]]] }
    var sent = false
    model.commandRequest = { _ in sent = true; throw URLError(.badServerResponse) }
    model.retryJob("job-a")
    for _ in 0..<20 where model.feedback[.jobs] == nil { await Task.yield() }
    #expect(!sent)
    #expect(model.feedback[.jobs]?.message.contains("回收") == true)
}
