import Darwin
import Foundation

public enum DevelopmentLauncher {
    public static func start(paths: ApplicationPaths = ApplicationPaths()) throws -> Data {
        guard paths.isDevelopmentBuild, paths.diagnostic.runtimeInstalled,
              let app = paths.bundleURL else { throw ControlSocket.ControlError.unavailable }
        if let response = try? ControlSocket.request("service.status") { return response }
        let directory = URL(fileURLWithPath: ControlSocket.path).deletingLastPathComponent()
        if !FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                   attributes: [.posixPermissions: 0o700])
        }
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        guard attributes[.type] as? FileAttributeType == .typeDirectory,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700 else {
            throw ControlSocket.ControlError.unavailable
        }
        let logURL = directory.appendingPathComponent("development-helper.log")
        let descriptor = Darwin.open(logURL.path, O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw ControlSocket.ControlError.unavailable }
        let log = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        let process = Process()
        process.executableURL = app.appendingPathComponent("Contents/MacOS/ASRDesktopHelper")
        process.arguments = ["--serve"]
        var environment = ProcessInfo.processInfo.environment
        environment["ASR_DESKTOP_SERVICE_MODE"] = "development"
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = log
        process.standardError = log
        try process.run()
        for _ in 0..<100 {
            if let response = try? ControlSocket.request("service.status") { return response }
            if !process.isRunning { break }
            Thread.sleep(forTimeInterval: 0.05)
        }
        throw ControlSocket.ControlError.unavailable
    }
}
