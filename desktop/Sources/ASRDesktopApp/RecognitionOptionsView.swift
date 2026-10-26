import SwiftUI

struct RecognitionOptionsView: View {
    @Binding var options: RecognitionOptions
    let models: [[String: Any]]

    private var execution: [String: Any] {
        models.first { $0["id"] as? String == options.model }?["execution"] as? [String: Any] ?? [:]
    }
    private var supportsGPU: Bool { (execution["devices"] as? [String] ?? ["cpu", "mps"]).contains("mps") }
    private var supportsHotwords: Bool { execution["hotwords"] as? Bool ?? true }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("模型", selection: $options.model) {
                    if !models.contains(where: { $0["id"] as? String == options.model }) {
                        Text(options.model).tag(options.model)
                    }
                    ForEach(models.compactMap { $0["id"] as? String }, id: \.self) { id in
                        Text(models.first { $0["id"] as? String == id }?["display_name"] as? String ?? id).tag(id)
                    }
                }
                Picker("文字", selection: $options.script) {
                    Text("台灣繁體").tag("traditional")
                    Text("簡體").tag("simplified")
                    Text("原文").tag("original")
                }
            }
            HStack {
                Text("輸出格式")
                Toggle("TXT", isOn: $options.includeTXT)
                Toggle("SRT", isOn: $options.includeSRT)
                Toggle("JSON", isOn: $options.includeJSON)
            }
            DisclosureGroup("進階辨識與字幕選項") {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("執行裝置", selection: $options.device) {
                        Text("自動").tag("auto"); Text("CPU").tag("cpu")
                        if supportsGPU { Text("GPU").tag("gpu") }
                    }
                    LabeledContent("辨識語言") { TextField("辨識語言", text: $options.language) }
                    LabeledContent("熱詞") { TextField("以逗號分隔", text: $options.hotwords).accessibilityLabel("熱詞，以逗號分隔") }
                        .disabled(!supportsHotwords)
                    if !supportsHotwords { Text("此模型未提供熱詞設定").font(.callout) }
                    Stepper("字幕每行最多 \(options.maxChars) 單位", value: $options.maxChars, in: 1...100)
                    Stepper("字幕最長 \(Double(options.maxDuration) / 1000, specifier: "%.2f") 秒", value: $options.maxDuration, in: 250...30000, step: 250)
                    Toggle("明確允許覆寫既有輸出", isOn: $options.overwrite)
                    Text("JSON 保留原始辨識文字；覆寫不會改動來源影音。").font(.callout)
                }.padding(.top, 8)
            }
        }
        .onChange(of: options.model) {
            if !supportsGPU && ["gpu", "mps"].contains(options.device) { options.device = "auto" }
            if !supportsHotwords { options.hotwords = "" }
        }
    }
}
