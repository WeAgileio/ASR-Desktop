import Foundation
import Testing
@testable import ASRDesktopCore

func releaseFixture(_ tag: String, id: Int = 1, draft: Bool = false, asset: Bool = true,
                    prerelease: Bool? = nil, size: Int = 100, url: String? = nil) throws -> DesktopRelease {
    let value: [String: Any] = ["id": id, "tag_name": tag, "draft": draft,
        "prerelease": prerelease ?? tag.contains("beta"),
        "html_url": url ?? "https://github.com/WeAgileio/ASR-Desktop/releases/tag/\(tag)",
        "body": " ", "assets": asset ? [["name": "ASR-Desktop-\(tag)-arm64.dmg", "state": "uploaded", "size": size]] : []]
    return try JSONDecoder().decode(DesktopRelease.self, from: JSONSerialization.data(withJSONObject: value))
}

@Test func releaseVersionComparison() throws {
    #expect(ReleaseVersion("0.2.0b2") == ReleaseVersion("v0.2.0-beta.2"))
    #expect(try #require(ReleaseVersion("0.2.0b2")) < #require(ReleaseVersion("0.2.0b10")))
    #expect(try #require(ReleaseVersion("0.2.0b10")) < #require(ReleaseVersion("0.2.0")))
    #expect(try #require(ReleaseVersion("0.9.9")) < #require(ReleaseVersion("1.0.0b1")))
    for invalid in [nil, "", "0.2", "0.2.0rc1", "0.2.0 extra", "01.2.0", "0.2.0b99999999999999999999999"] as [String?] {
        #expect(ReleaseVersion(invalid) == nil)
    }
    #expect(ReleaseVersion("0.2.0b2")?.tag == "v0.2.0-beta.2")
}

@Test func releaseSelectionFiltersAndSorts() throws {
    let current = try #require(ReleaseVersion("0.2.0b2"))
    let values = try [releaseFixture("v0.2.0-beta.10", id: 2), releaseFixture("v0.2.0", id: 3),
                      releaseFixture("v9.0.0", draft: true), releaseFixture("v8.0.0", asset: false),
                      releaseFixture("v7.0.0", prerelease: true), releaseFixture("v6.0.0", size: 0),
                      releaseFixture("v0.2.0-beta.2")]
    #expect(try DesktopRelease.candidate(in: values, current: current)?.tag_name == "v0.2.0")
    #expect(try DesktopRelease.candidate(in: values, current: current, supportedPlatform: false) == nil)
    #expect(try DesktopRelease.candidate(in: [releaseFixture("v1.0.0-beta.1")], current: #require(ReleaseVersion("0.2.0"))) == nil)
    #expect(try DesktopRelease.candidate(in: [], current: current) == nil)
    #expect(throws: ReleaseCheckError.self) { try DesktopRelease.candidate(in: [releaseFixture("v1.0.0"), releaseFixture("v1.0.0", id: 2)], current: current) }
    #expect(throws: ReleaseCheckError.self) { try DesktopRelease.candidate(in: [releaseFixture("v1.0.0", url: "https://evil.example")], current: current) }
    #expect(try releaseFixture("v1.0.0").notes == "未提供更新說明。")
}
