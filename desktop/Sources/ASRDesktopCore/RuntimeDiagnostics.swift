import Foundation

public struct RuntimeDiagnosticResult: Sendable {
    public let data: Data
    public let status: Int32
}

public enum RuntimeDiagnostics {
    public static func run(paths: ApplicationPaths = ApplicationPaths()) throws -> RuntimeDiagnosticResult {
        let installation = try JSONSerialization.jsonObject(with: paths.diagnostic.jsonData())
        var runtime: [String: Any] = [:]
        var status: Int32 = 3
        if paths.diagnostic.platformSupported && paths.diagnostic.runtimeInstalled,
           let executable = paths.runtimeExecutable {
            let process = Process()
            process.executableURL = executable
            process.arguments = ["--diagnose"]
            var environment = ProcessInfo.processInfo.environment
            for key in ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE"] { environment.removeValue(forKey: key) }
            environment["PYTHONNOUSERSITE"] = "1"
            if let root = paths.bundleURL { environment["ASR_DESKTOP_BUNDLE"] = root.path }
            process.environment = environment
            let output = Pipe()
            process.standardOutput = output
            process.standardError = FileHandle.standardError
            process.standardInput = FileHandle.nullDevice
            do {
                try process.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                runtime = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
                status = process.terminationStatus == 0 && runtime["ready"] as? Bool == true ? 0 : 3
            } catch {
                runtime = ["ready": false, "error": error.localizedDescription]
            }
        } else {
            runtime = ["ready": false, "error": "內建元件缺失或平台不相容，請重新安裝完整 App。"]
        }
        let data = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "installation": installation,
                                                               "runtime": runtime, "ready": status == 0], options: [.sortedKeys])
        return RuntimeDiagnosticResult(data: data + Data([10]), status: status)
    }
}
