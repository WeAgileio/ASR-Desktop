import Foundation

struct RecognitionOptions: Equatable {
    var model = "fun-asr-nano"
    var device = "auto"
    var script = "traditional"
    var includeTXT = true
    var includeSRT = true
    var includeJSON = false
    var language = "中文"
    var hotwords = ""
    var maxChars = 20
    var maxDuration = 5000
    var overwrite = false

    init() {}

    init(_ values: [String: Any]) {
        model = values["model"] as? String ?? model
        device = values["device"] as? String ?? device
        if device == "mps" { device = "gpu" }
        script = values["script"] as? String ?? script
        if let formats = values["formats"] as? [String] {
            includeTXT = formats.contains("txt")
            includeSRT = formats.contains("srt")
            includeJSON = formats.contains("json")
        }
        language = values["language"] as? String ?? language
        hotwords = (values["hotwords"] as? [String] ?? []).joined(separator: ", ")
        maxChars = values["max_chars"] as? Int ?? maxChars
        maxDuration = values["max_duration_ms"] as? Int ?? maxDuration
        overwrite = values["overwrite"] as? Bool ?? overwrite
    }

    var formats: [String] {
        (includeTXT ? ["txt"] : []) + (includeSRT ? ["srt"] : []) + (includeJSON ? ["json"] : [])
    }

    var dictionary: [String: Any] {
        ["model": model, "device": device, "script": script, "formats": formats,
         "language": language, "hotwords": hotwords.split(separator: ",").map {
             $0.trimmingCharacters(in: .whitespaces)
         }.filter { !$0.isEmpty }, "max_chars": maxChars,
         "max_duration_ms": maxDuration, "overwrite": overwrite]
    }
}
