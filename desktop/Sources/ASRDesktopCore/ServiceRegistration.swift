import Foundation
import ServiceManagement

@MainActor
public enum ServiceRegistration {
    public static let plistName = "io.asrsrt.desktop.agent.plist"

    public static func perform(_ action: String) -> (Data, Int32) {
        let service = SMAppService.agent(plistName: plistName)
        var result: [String: Any] = ["schema_version": 1]
        var exitCode: Int32 = 0
        do {
            switch action {
            case "register":
                if service.status == .enabled {
                    let process = Process()
                    process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
                    process.arguments = ["kickstart", "gui/\(getuid())/io.asrsrt.desktop.agent"]
                    let errors = Pipe()
                    process.standardError = errors
                    process.standardOutput = FileHandle.nullDevice
                    try process.run()
                    let message = errors.fileHandleForReading.readDataToEndOfFile()
                    process.waitUntilExit()
                    if process.terminationStatus != 0 {
                        throw NSError(domain: "ASRDesktop.Service", code: Int(process.terminationStatus),
                                      userInfo: [NSLocalizedDescriptionKey: String(decoding: message, as: UTF8.self)])
                    }
                } else if service.status != .requiresApproval {
                    try service.register()
                }
            case "unregister":
                if service.status != .notRegistered { try service.unregister() }
            case "status": break
            default:
                result["error"] = ["code": "invalid_arguments", "message": "Unknown service registration action"]
                exitCode = 2
            }
        } catch {
            let native = error as NSError
            result["error"] = ["code": "service_registration_failed", "message": native.localizedDescription,
                               "domain": native.domain, "native_code": native.code]
            exitCode = 3
        }
        switch service.status {
        case .enabled: result["registration_state"] = "enabled"
        case .notRegistered: result["registration_state"] = "not_registered"
        case .requiresApproval:
            result["registration_state"] = "requires_approval"
            result["guidance"] = "請在系統設定的登入項目中允許 ASR Desktop 背景執行。"
            exitCode = 3
        case .notFound: result["registration_state"] = "not_found"
        @unknown default:
            result["registration_state"] = "unknown"
            exitCode = 3
        }
        let data = (try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])) ?? Data("{}".utf8)
        return (data + Data([10]), exitCode)
    }
}

public enum AppServiceBridge {
    public static func run(_ action: String, paths: ApplicationPaths = ApplicationPaths()) throws -> (Data, Int32) {
        guard let root = paths.bundleURL else { throw RuntimeBridge.RuntimeError.notInstalled }
        let process = Process()
        process.executableURL = root.appendingPathComponent("Contents/MacOS/ASRDesktopApp")
        process.arguments = ["--service-control", action]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return (data, process.terminationStatus)
    }
}
