import Foundation
import Testing
@testable import ASRDesktopCore

@Test func durationsAndQueryGenerations() {
    #expect(MediaDuration.text(nil) == "時長未知")
    #expect(MediaDuration.text(0) == "時長未知")
    #expect(MediaDuration.text(500) == "小於 1 秒")
    #expect(MediaDuration.text(61999) == "1:01")
    #expect(MediaDuration.text(3661000) == "1:01:01")
    var state = QueryState()
    let first = state.begin()!
    state.change()
    #expect(!state.accepts(first))
    #expect(state.begin() == nil)
    let pending = state.finish()
    #expect(pending)
    let latest = state.begin()!
    #expect(state.accepts(latest))
    let finished = state.finish()
    #expect(!finished)
    #expect(!TaskCapabilities.supports(["jobs.list"]))
    #expect(TaskCapabilities.supports(Array(TaskCapabilities.required)))
}

@Test @MainActor func finderUsesFileURLsAndRejectsMissingPaths() throws {
    let paths = ["/tmp/中文 folder/nested/a.txt", "/tmp/中文 folder/nested/a.srt", "/tmp/中文 folder/nested/a.json"]
    var received: [URL] = []
    try FinderLocation.reveal(paths, exists: { _ in true }, open: { received = $0; return true })
    #expect(received.map(\.path) == paths)
    let files = received.allSatisfy { $0.isFileURL }
    #expect(files)
    #expect(throws: FinderLocation.LocationError.self) { try FinderLocation.reveal(paths, exists: { _ in false }, open: { _ in Issue.record("must not open"); return true }) }
    #expect(throws: FinderLocation.LocationError.self) { try FinderLocation.reveal(paths, exists: { _ in true }, open: { _ in false }) }
    #expect(throws: FinderLocation.LocationError.self) { try FinderLocation.reveal([]) }
}
