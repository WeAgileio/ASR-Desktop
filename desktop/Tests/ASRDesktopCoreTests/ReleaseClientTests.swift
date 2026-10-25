import Foundation
import Testing
@testable import ASRDesktopCore

actor ReplyQueue {
    var replies: [ReleaseHTTPReply]
    var requests: [URLRequest] = []
    init(_ replies: [ReleaseHTTPReply]) { self.replies = replies }
    func send(_ request: URLRequest) throws -> ReleaseHTTPReply {
        requests.append(request)
        guard !replies.isEmpty else { throw URLError(.timedOut) }
        return replies.removeFirst()
    }
}

@Test func releasePaginationAndRequestPrivacy() async throws {
    let queue = ReplyQueue([
        ReleaseHTTPReply(data: Data("[]".utf8), headers: ["Link": "<https://api.github.com/repos/WeAgileio/ASR-Desktop/releases?per_page=100&page=2>; rel=\"next\""]),
        ReleaseHTTPReply(data: Data("[]".utf8))])
    let client = ReleaseClient { try await queue.send($0) }
    #expect(try await client.fetch().isEmpty)
    let requests = await queue.requests
    #expect(requests.count == 2)
    #expect(requests.allSatisfy { $0.httpBody == nil && $0.value(forHTTPHeaderField: "Authorization") == nil && $0.httpMethod == "GET" })
    #expect(requests[1].url?.query?.contains("page=2") == true)
}

@Test func releaseHTTPFailuresAndBounds() async throws {
    let date = Date(timeIntervalSince1970: 1000)
    for status in [403, 404, 500] {
        let client = ReleaseClient { _ in ReleaseHTTPReply(data: Data(), status: status) }
        do { _ = try await client.fetch(now: date); Issue.record("must fail") }
        catch ReleaseCheckError.http(let code) { #expect(code == status) }
    }
    for status in [403, 429] {
        let client = ReleaseClient { _ in ReleaseHTTPReply(data: Data(), status: status, headers: ["Retry-After": "120"]) }
        do { _ = try await client.fetch(now: date); Issue.record("must rate limit") }
        catch ReleaseCheckError.rateLimited(let until) { #expect(until == date.addingTimeInterval(120)) }
    }
    for reply in [ReleaseHTTPReply(data: Data("not json".utf8)),
                  ReleaseHTTPReply(data: Data(repeating: 32, count: 2 * 1024 * 1024 + 1)),
                  ReleaseHTTPReply(data: Data("[]".utf8), headers: ["Link": "<https://evil.example/releases>; rel=\"next\""]),
                  ReleaseHTTPReply(data: Data("[]".utf8), headers: ["Link": "<\(ReleaseClient.endpoint)>; rel=\"next\""])] {
        let client = ReleaseClient { _ in reply }
        await #expect(throws: ReleaseCheckError.self) { try await client.fetch() }
    }
    let offline = ReleaseClient { _ in throw URLError(.notConnectedToInternet) }
    await #expect(throws: URLError.self) { try await offline.fetch() }
}

@Test @MainActor func releasePreferencesAndBrowser() async throws {
    let suite = "asr-update-test-" + UUID().uuidString
    let prefs = try #require(UserDefaults(suiteName: suite))
    defer { prefs.removePersistentDomain(forName: suite) }
    var date = Date(timeIntervalSince1970: 1000)
    var calls = 0
    var fail = false
    let release = try releaseFixture("v0.3.0-beta.1")
    let updates = ReleaseUpdates(current: ReleaseVersion("0.2.0b2"), preferences: prefs, now: { date }) {
        calls += 1
        if fail { throw URLError(.notConnectedToInternet) }
        return [release]
    }
    await updates.check()
    #expect(calls == 1 && updates.showNotice)
    #expect(updates.currentLabel == "v0.2.0-beta.2")
    updates.later(); await updates.check()
    #expect(calls == 1 && !updates.showNotice)
    await updates.check(manual: true); updates.skip()
    date = date.addingTimeInterval(86400)
    await updates.check()
    #expect(calls == 3 && !updates.showNotice)
    await updates.check(manual: true)
    #expect(updates.showNotice)
    var opened: URL?
    updates.openDownload { opened = $0; return false }
    #expect(opened?.absoluteString == release.html_url)
    #expect(updates.message.contains("無法開啟"))
    updates.openDownload { _ in true }
    #expect(!updates.showNotice)
    let success = updates.lastSuccess
    fail = true; await updates.check(manual: true)
    #expect(updates.lastSuccess == success && updates.message.contains("檢查失敗"))
    updates.setAutomatic(false)
    let reopened = ReleaseUpdates(current: ReleaseVersion("0.2.0b2"), preferences: prefs)
    #expect(!reopened.automatic && reopened.lastSuccess == success)
}

@Test @MainActor func releaseInFlightAndRateLimit() async throws {
    let suite = "asr-update-test-" + UUID().uuidString
    let prefs = try #require(UserDefaults(suiteName: suite))
    defer { prefs.removePersistentDomain(forName: suite) }
    var resume: CheckedContinuation<[DesktopRelease], any Error>?
    var calls = 0
    let updates = ReleaseUpdates(current: ReleaseVersion("0.2.0b2"), preferences: prefs, fetch: {
        calls += 1
        return try await withCheckedThrowingContinuation { resume = $0 }
    })
    let task = Task { await updates.check() }
    while resume == nil { await Task.yield() }
    await updates.check(manual: true)
    #expect(calls == 1)
    updates.setAutomatic(false)
    resume?.resume(returning: [try releaseFixture("v1.0.0")])
    await task.value
    #expect(updates.candidate == nil && !updates.showNotice && updates.lastSuccess == nil)
    let until = Date().addingTimeInterval(120)
    let limited = ReleaseUpdates(current: ReleaseVersion("1.0.0"), preferences: prefs, fetch: {
        calls += 1; throw ReleaseCheckError.rateLimited(until)
    })
    await limited.check(manual: true); await limited.check(manual: true)
    #expect(calls == 2)
    #expect(limited.message.contains("限制"))
}

@Test func releaseSecondPageCandidateAndIncompleteResults() async throws {
    let body = #"[{"id":1,"tag_name":"v0.3.0-beta.1","draft":false,"prerelease":true,"html_url":"https://github.com/WeAgileio/ASR-Desktop/releases/tag/v0.3.0-beta.1","body":"notes","assets":[{"name":"ASR-Desktop-v0.3.0-beta.1-arm64.dmg","state":"uploaded","size":123}]}]"#
    let queue = ReplyQueue([
        ReleaseHTTPReply(data: Data("[]".utf8), headers: ["Link": "<https://api.github.com/repos/WeAgileio/ASR-Desktop/releases?page=2>; rel=\"next\""]),
        ReleaseHTTPReply(data: Data(body.utf8))])
    let values = try await ReleaseClient { try await queue.send($0) }.fetch()
    #expect(try DesktopRelease.candidate(in: values, current: ReleaseVersion("0.2.0b2")!, supportedPlatform: true)?.tag_name == "v0.3.0-beta.1")
    let incomplete = ReplyQueue([ReleaseHTTPReply(data: Data(body.utf8), headers: ["Link": "<https://api.github.com/repos/WeAgileio/ASR-Desktop/releases?page=2>; rel=\"next\""])])
    await #expect(throws: URLError.self) { try await ReleaseClient { try await incomplete.send($0) }.fetch() }
    let pages = (1...10).map { page in
        ReleaseHTTPReply(data: Data("[]".utf8), headers: ["Link": "<https://api.github.com/repos/WeAgileio/ASR-Desktop/releases?page=\(page + 1)>; rel=\"next\""])
    }
    let tooMany = ReplyQueue(pages)
    await #expect(throws: ReleaseCheckError.self) { try await ReleaseClient { try await tooMany.send($0) }.fetch() }
}

@Test @MainActor func releaseSkipSurvivesRelaunchAndNewVersion() async throws {
    let suite = "asr-update-test-" + UUID().uuidString
    let prefs = try #require(UserDefaults(suiteName: suite))
    defer { prefs.removePersistentDomain(forName: suite) }
    var date = Date(timeIntervalSince1970: 1000)
    var release = try releaseFixture("v0.3.0-beta.1")
    let first = ReleaseUpdates(current: ReleaseVersion("0.2.0b2"), preferences: prefs, now: { date }, fetch: { [release] })
    await first.check(); first.skip()
    date = date.addingTimeInterval(86400)
    let second = ReleaseUpdates(current: ReleaseVersion("0.2.0b2"), preferences: prefs, now: { date }, fetch: { [release] })
    await second.check()
    #expect(!second.showNotice && second.candidate != nil)
    release = try releaseFixture("v0.3.0-beta.2")
    date = date.addingTimeInterval(86400)
    await second.check()
    #expect(second.showNotice)
    let unknown = ReleaseUpdates(current: nil, preferences: prefs, fetch: { Issue.record("must not request"); return [] })
    await unknown.check(manual: true)
    #expect(unknown.currentLabel == "版本未知" && unknown.message.contains("未知"))
}
