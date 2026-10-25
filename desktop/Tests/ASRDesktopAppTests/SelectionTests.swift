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
