import Foundation

enum WorkspacePane: String, CaseIterable {
    case intake, jobs, models, settings
}

enum ServiceConnection: String {
    case connecting = "服務連線中"
    case ready = "服務已連線"
    case unavailable = "服務未連線"
    case incompatible = "服務版本不相容"
    case stopping = "服務正在停止"
}

struct OperationFeedback: Equatable {
    enum Kind { case working, success, failure, uncertain }
    var title: String
    var message: String
    var kind: Kind
}

enum JobPresentation {
    static func canCancel(_ job: [String: Any]) -> Bool {
        ["queued", "blocked", "running"].contains(job["state"] as? String ?? "")
    }
    static func canRetry(_ job: [String: Any], stopped: Bool) -> Bool {
        stopped && ["failed", "cancelled", "interrupted"].contains(job["state"] as? String ?? "")
    }
    static func canRemove(_ job: [String: Any], stopped: Bool) -> Bool {
        stopped && !["running", "cancelling"].contains(job["state"] as? String ?? "")
    }
    static func hasOutputs(_ job: [String: Any]) -> Bool {
        !(job["delivered_outputs"] as? [String: String] ?? [:]).isEmpty
    }
    static func fraction(_ progress: [String: Any]) -> Double? {
        guard ["actual", "estimated"].contains(progress["progress_kind"] as? String ?? ""),
              let current = progress["current"] as? Double, current.isFinite, current >= 0,
              let total = progress["total"] as? Double, total.isFinite, total > 0,
              current <= total else { return nil }
        return current / total
    }
}
