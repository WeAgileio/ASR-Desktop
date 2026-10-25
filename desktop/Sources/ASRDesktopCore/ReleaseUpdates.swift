import Foundation
import Combine

@MainActor
public final class ReleaseUpdates: ObservableObject {
    @Published public private(set) var checking = false
    @Published public private(set) var message = "尚未檢查更新。"
    @Published public private(set) var candidate: DesktopRelease?
    @Published public private(set) var lastSuccess: Date?
    @Published public private(set) var automatic: Bool
    @Published public var showNotice = false
    public let current: ReleaseVersion?
    public var currentLabel: String { current?.tag ?? "版本未知" }
    private let preferences: UserDefaults
    private let now: () -> Date
    private let fetch: () async throws -> [DesktopRelease]
    private let supportedPlatform: Bool
    private var generation = 0
    private var requestIsManual = false
    private var retryAfter: Date?
    private static let prefix = "releaseUpdates."

    public init(current: ReleaseVersion? = .current(), preferences: UserDefaults = .standard,
                supportedPlatform: Bool = ReleaseUpdates.platformSupported,
                now: @escaping () -> Date = { Date() },
                fetch: @escaping () async throws -> [DesktopRelease] = { try await ReleaseClient().fetch() }) {
        self.current = current; self.preferences = preferences; self.supportedPlatform = supportedPlatform
        self.now = now; self.fetch = fetch
        self.automatic = preferences.object(forKey: Self.prefix + "automatic") as? Bool ?? true
        self.lastSuccess = preferences.object(forKey: Self.prefix + "lastSuccess") as? Date
        self.retryAfter = preferences.object(forKey: Self.prefix + "retryAfter") as? Date
    }
    public static var platformSupported: Bool {
        #if arch(arm64)
        ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 14
        #else
        false
        #endif
    }
    public func setAutomatic(_ value: Bool) {
        automatic = value; preferences.set(value, forKey: Self.prefix + "automatic")
        if !value && checking && !requestIsManual { generation += 1; showNotice = false }
    }
    public func later() { showNotice = false }
    public func skip() {
        if let version = candidate?.version { preferences.set(version.tag, forKey: Self.prefix + "skipped") }
        showNotice = false
    }
    public func openDownload(using open: (URL) -> Bool) {
        guard let url = candidate?.downloadPage else { message = "下載頁連結無效。"; return }
        if open(url) { showNotice = false }
        else { message = "無法開啟下載頁，請檢查預設瀏覽器後重試。" }
    }
    public func check(manual: Bool = false) async {
        guard !checking else { return }
        let date = now()
        if !manual {
            guard automatic else { return }
            if let attempt = preferences.object(forKey: Self.prefix + "lastAutomaticAttempt") as? Date,
               date.timeIntervalSince(attempt) < 86400 { return }
        }
        if let retryAfter, date < retryAfter { message = ReleaseCheckError.rateLimited(retryAfter).localizedDescription; return }
        guard let current else { message = "目前 App 版本未知，無法判斷更新。"; return }
        guard supportedPlatform else { message = "目前僅提供 macOS 14 以上 Apple Silicon 安裝包。"; return }
        if !manual { preferences.set(date, forKey: Self.prefix + "lastAutomaticAttempt") }
        checking = true; requestIsManual = manual; generation += 1
        let ticket = generation
        message = "正在檢查更新…"; showNotice = false; candidate = nil
        defer { checking = false }
        do {
            let releases = try await fetch()
            guard ticket == generation else { message = "已停止自動檢查提醒。"; return }
            candidate = try DesktopRelease.candidate(in: releases, current: current, supportedPlatform: supportedPlatform)
            lastSuccess = now(); preferences.set(lastSuccess, forKey: Self.prefix + "lastSuccess")
            retryAfter = nil; preferences.removeObject(forKey: Self.prefix + "retryAfter")
            if let candidate {
                message = "有可用更新：\(candidate.version!.tag)"
                showNotice = manual || preferences.string(forKey: Self.prefix + "skipped") != candidate.version?.tag
            } else { message = releases.isEmpty ? "目前沒有可下載版本。" : "沒有可用更新。" }
        } catch {
            guard ticket == generation else { message = "已停止自動檢查提醒。"; return }
            if case ReleaseCheckError.rateLimited(let date) = error {
                retryAfter = date; preferences.set(date, forKey: Self.prefix + "retryAfter")
            }
            let detail: String
            if let network = error as? URLError {
                detail = network.code == .timedOut ? "連線逾時，請稍後重試。" : "無法連線至 GitHub，請檢查網路後重試。"
            } else { detail = error.localizedDescription }
            message = "檢查失敗：\(detail)" + (lastSuccess == nil ? "" : "（上次成功紀錄並非本次結果）")
        }
    }
}
