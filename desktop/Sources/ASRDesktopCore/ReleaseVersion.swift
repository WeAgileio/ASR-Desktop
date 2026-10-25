import Foundation

public struct ReleaseVersion: Hashable, Comparable, Sendable {
    public let major: Int
    public let minor: Int
    public let patch: Int
    public let beta: Int?

    public init?(_ raw: String?) {
        guard let raw,
              let match = raw.wholeMatch(of: /v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:(?:b|-beta\.)(0|[1-9][0-9]*))?/),
              let major = Int(match.1), let minor = Int(match.2), let patch = Int(match.3) else { return nil }
        let beta = match.4.flatMap { Int($0) }
        if match.4 != nil && beta == nil { return nil }
        self.major = major; self.minor = minor; self.patch = patch; self.beta = beta
    }
    public static func current(in bundle: Bundle = .main) -> Self? {
        Self(bundle.object(forInfoDictionaryKey: "ASRDesktopReleaseVersion") as? String)
    }
    public var tag: String { "v\(major).\(minor).\(patch)" + (beta.map { "-beta.\($0)" } ?? "") }
    public static func < (lhs: Self, rhs: Self) -> Bool {
        let a = [lhs.major, lhs.minor, lhs.patch], b = [rhs.major, rhs.minor, rhs.patch]
        if a != b { return a.lexicographicallyPrecedes(b) }
        switch (lhs.beta, rhs.beta) {
        case let (a?, b?): return a < b
        case (_?, nil): return true
        default: return false
        }
    }
}

public struct DesktopRelease: Decodable, Sendable, Equatable {
    public struct Asset: Decodable, Sendable, Equatable {
        public let name: String
        public let state: String
        public let size: Int64
    }
    public let id: Int64
    public let tag_name: String
    public let draft: Bool
    public let prerelease: Bool
    public let html_url: String
    public let body: String?
    public let assets: [Asset]
    public var version: ReleaseVersion? { ReleaseVersion(tag_name) }
    public var notes: String {
        let text = body?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return text.isEmpty ? "未提供更新說明。" : String(text.prefix(12000))
    }
    public var downloadPage: URL? {
        guard let version, tag_name == version.tag,
              html_url == "https://github.com/WeAgileio/ASR-Desktop/releases/tag/\(tag_name)" else { return nil }
        return URL(string: html_url)
    }
    public static func candidate(in releases: [Self], current: ReleaseVersion, supportedPlatform: Bool = true) throws -> Self? {
        guard supportedPlatform else { return nil }
        var candidates: [ReleaseVersion: Self] = [:]
        for release in releases {
            guard !release.draft, let version = release.version, version > current,
                  release.tag_name == version.tag, release.prerelease == (version.beta != nil),
                  current.beta != nil || version.beta == nil,
                  release.assets.contains(where: { $0.name == "ASR-Desktop-\(release.tag_name)-arm64.dmg" && $0.state == "uploaded" && $0.size > 0 }) else { continue }
            guard release.downloadPage != nil else { throw ReleaseCheckError.invalidResponse }
            if let previous = candidates[version], previous.id != release.id { throw ReleaseCheckError.ambiguousVersion }
            candidates[version] = release
        }
        return candidates.keys.max().flatMap { candidates[$0] }
    }
}

public enum ReleaseCheckError: Error, LocalizedError, Sendable {
    case invalidResponse, incomplete, ambiguousVersion, http(Int), rateLimited(Date)
    public var errorDescription: String? {
        switch self {
        case .invalidResponse: "更新資料或下載連結格式無效。"
        case .incomplete: "未能完整取得版本清單，請稍後重試。"
        case .ambiguousVersion: "發布清單含有重複版本，無法判斷更新。"
        case .http(let code): "無法取得發布資料（HTTP \(code)），請確認網路或稍後重試。"
        case .rateLimited(let date): "GitHub 暫時限制檢查次數，請於 \(date.formatted()) 後重試。"
        }
    }
}
