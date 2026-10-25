import AppKit
import Foundation

public enum MediaDuration {
    public static func text(_ milliseconds: Double?) -> String {
        guard let milliseconds, milliseconds.isFinite, milliseconds > 0 else { return "時長未知" }
        if milliseconds < 1000 { return "小於 1 秒" }
        let seconds = Int(milliseconds / 1000)
        if seconds < 3600 { return String(format: "%d:%02d", seconds / 60, seconds % 60) }
        return String(format: "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
    }
}

public struct QueryState: Sendable {
    public private(set) var generation = 0
    public private(set) var refreshing = false
    public private(set) var pending = false
    public init() {}
    public mutating func change() { generation += 1; pending = true }
    public mutating func begin() -> Int? {
        if refreshing { pending = true; return nil }
        refreshing = true; pending = false
        return generation
    }
    public func accepts(_ value: Int) -> Bool { value == generation }
    public mutating func finish() -> Bool { refreshing = false; return pending }
}

public enum TaskCapabilities {
    public static let required: Set<String> = ["batches.list", "batches.rename", "jobs.list.query", "jobs.retry.selection", "jobs.selection.preview", "jobs.remove", "intake.inspect"]
    public static func supports(_ capabilities: [String]) -> Bool { required.isSubset(of: Set(capabilities)) }
}

@MainActor
public enum FinderLocation {
    public static func reveal(_ paths: [String], exists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) },
                              open: ([URL]) -> Bool = { urls in
                                  guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.finder") != nil else { return false }
                                  NSWorkspace.shared.activateFileViewerSelecting(urls)
                                  return NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.finder").contains { !$0.isTerminated }
                              }) throws {
        guard !paths.isEmpty else { throw LocationError.noOutputs }
        guard paths.allSatisfy({ !$0.isEmpty && $0.hasPrefix("/") && exists($0) }) else { throw LocationError.missing }
        guard open(paths.map { URL(fileURLWithPath: $0) }) else { throw LocationError.failed }
    }
    public enum LocationError: LocalizedError {
        case noOutputs, missing, failed
        public var errorDescription: String? {
            switch self {
            case .noOutputs: "尚無已交付成果。"
            case .missing: "路徑不存在，檔案可能已搬移或刪除。"
            case .failed: "無法開啟 Finder，請稍後再試。"
            }
        }
    }
}
