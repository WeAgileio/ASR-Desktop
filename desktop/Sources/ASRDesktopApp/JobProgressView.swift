import SwiftUI

struct JobProgressView: View {
    let progress: [String: Any]
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(progress["message"] as? String ?? progress["phase"] as? String ?? "處理中")
                .font(.callout)
            if let fraction = JobPresentation.fraction(progress) {
                ProgressView(value: fraction)
                Text("\(progress["progress_kind"] as? String == "estimated" ? "估計" : "實際")進度 \(Int(fraction * 100))%").font(.callout)
            } else if !compact {
                ProgressView().controlSize(.small).accessibilityLabel("處理中，沒有可量化進度")
            }
            if !compact {
                if let elapsed = progress["elapsed_seconds"] as? Double, elapsed.isFinite, elapsed >= 0 {
                    Text("階段已用 \(elapsed, specifier: "%.0f") 秒").font(.callout)
                }
                if let eta = progress["eta_seconds"] as? Double, eta.isFinite, eta >= 0 {
                    Text("估計剩餘 \(eta, specifier: "%.0f") 秒").font(.callout)
                }
            }
        }
    }
}
