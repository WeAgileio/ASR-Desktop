import Testing
@testable import ASRDesktopApp

@Test @MainActor func selectionSurvivesPagingButNotNewConditions() {
    // No connection: exercise the actual view model without starting a helper.
    let model = DesktopModel()
    model.selectedIDs = ["job-a", "job-b"]
    model.detail = ["id": "job-a"]
    model.changePage(100)
    #expect(model.selectedCount == 2)
    #expect(model.currentSelection["ids"] as? [String] == ["job-a", "job-b"])
    #expect(model.detail?["id"] as? String == "job-a")
    model.query = "訪談"
    #expect(model.offset == 0)
    #expect(model.selectedCount == 0)
    #expect(model.detail == nil)

    model.allSelection = ["total": 120, "selector": ["query": "訪談"], "target_token": "snapshot"]
    model.changePage(100)
    #expect(model.selectedCount == 120)
    #expect(model.currentSelection["query"] as? String == "訪談")
    model.states = ["failed", "cancelled"]
    #expect(model.offset == 0)
    #expect(model.allSelection == nil)
    model.selectedIDs = ["job-a"]
    model.changePage(100)
    model.batchID = "another-batch"
    #expect(model.offset == 0)
    #expect(model.selectedIDs.isEmpty)
}

@Test @MainActor func detailPresentationDoesNotChangeQueryOrSelection() {
    let model = DesktopModel()
    model.batchID = "batch-a"; model.query = "訪談"; model.states = ["failed"]
    model.changePage(100)
    model.selectedIDs = ["job-a"]
    model.detail = ["id": "job-b"]
    model.showingDetail = true
    model.returnToList()
    #expect(model.batchID == "batch-a" && model.query == "訪談")
    #expect(model.states == ["failed"] && model.offset == 100)
    #expect(model.selectedIDs == ["job-a"])
    #expect(model.detail?["id"] as? String == "job-b")
    model.allSelection = ["total": 120, "selector": ["query": "訪談"], "target_token": "snapshot"]
    model.returnToList()
    #expect(model.selectedCount == 120)
    model.setSelected("job-b", checked: true)
    #expect(model.selectedIDs == ["job-b"] && model.allSelection == nil)
    #expect(model.feedback[.jobs]?.message.contains("個別勾選") == true)
    model.clearFilters()
    #expect(model.offset == 0 && model.selectedCount == 0)
}

@Test @MainActor func operationScopesRemainDistinct() async {
    let model = DesktopModel()
    model.request = { operation, arguments in
        #expect(operation == "jobs.selection.preview")
        let selector = arguments["selector"] as? [String: Any] ?? [:]
        let total = selector["batch_id"] == nil ? (selector["ids"] == nil ? 120 : 1) : 200
        return ["selector": selector, "total": total, "cannot_remove": [], "target_token": "scope-\(total)"] as [String: Any]
    }
    model.allSelection = ["total": 120, "selector": ["query": "訪談"], "target_token": "scope-120"]
    #expect(model.currentSelection["query"] as? String == "訪談")
    #expect(model.currentSelection["batch_id"] == nil)
    model.previewRemoval(["batch_id": "batch-a"], label: "整批")
    for _ in 0..<20 where model.removal == nil { await Task.yield() }
    #expect(model.removal?["total"] as? Int == 200)
    #expect((model.removal?["selector"] as? [String: Any])?["batch_id"] as? String == "batch-a")
    model.removal = nil // Cancelling the confirmation never sends a mutation.
    model.previewRemoval(["ids": ["job-b"]], label: "單筆")
    for _ in 0..<20 where model.removal == nil { await Task.yield() }
    #expect(model.removal?["total"] as? Int == 1)
    #expect(model.selectedCount == 120)
}
