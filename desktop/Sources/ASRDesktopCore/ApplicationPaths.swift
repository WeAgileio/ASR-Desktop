import Foundation
import Darwin

public struct ApplicationPaths: Sendable {
    public let bundleURL: URL?
    public let dataDirectory: URL

    public static var runningExecutableURL: URL {
        var size: UInt32 = 0
        _NSGetExecutablePath(nil, &size)
        var buffer = [CChar](repeating: 0, count: Int(size))
        guard _NSGetExecutablePath(&buffer, &size) == 0 else {
            return Bundle.main.executableURL ?? URL(fileURLWithPath: CommandLine.arguments[0])
        }
        let bytes = buffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }
        return URL(fileURLWithPath: String(decoding: bytes, as: UTF8.self))
    }

    public init(executableURL: URL = ApplicationPaths.runningExecutableURL,
                homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser) {
        var candidate = executableURL.standardizedFileURL.resolvingSymlinksInPath()
        var found: URL?
        for _ in 0..<12 {
            if candidate.pathExtension == "app" {
                found = candidate
                break
            }
            let parent = candidate.deletingLastPathComponent()
            if parent == candidate { break }
            candidate = parent
        }
        bundleURL = found
        dataDirectory = homeDirectory.appendingPathComponent("Library/Application Support/ASR Desktop", isDirectory: true)
    }

    public var runtimeExecutable: URL? {
        bundleURL?.appendingPathComponent("Contents/Resources/runtime/asr-desktop-runtime/asr-desktop-runtime")
    }

    public var isDevelopmentBuild: Bool {
        guard let url = bundleURL?.appendingPathComponent("Contents/Info.plist"),
              let data = try? Data(contentsOf: url),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return false }
        return plist["ASRDesktopDevelopmentMode"] as? Bool == true
    }

    public func mediaExecutable(_ name: String) -> URL? {
        guard name == "ffmpeg" || name == "ffprobe" else { return nil }
        return bundleURL?.appendingPathComponent("Contents/Resources/media/\(name)")
    }

    public var diagnostic: InstallationDiagnostic {
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "unsupported"
        #endif
        return InstallationDiagnostic(
            schemaVersion: 1,
            architecture: architecture,
            platformSupported: architecture == "arm64" && ProcessInfo.processInfo.isOperatingSystemAtLeast(
                OperatingSystemVersion(majorVersion: 14, minorVersion: 0, patchVersion: 0)),
            bundlePath: bundleURL?.path,
            dataPath: dataDirectory.path,
            runtimePresent: executableExists(runtimeExecutable),
            ffmpegPresent: executableExists(mediaExecutable("ffmpeg")),
            ffprobePresent: executableExists(mediaExecutable("ffprobe"))
        )
    }

    private func executableExists(_ url: URL?) -> Bool {
        guard let url else { return false }
        return FileManager.default.isExecutableFile(atPath: url.path)
    }
}

public struct InstallationDiagnostic: Codable, Sendable {
    public let schemaVersion: Int
    public let architecture: String
    public let platformSupported: Bool
    public let bundlePath: String?
    public let dataPath: String
    public let runtimePresent: Bool
    public let ffmpegPresent: Bool
    public let ffprobePresent: Bool

    public var runtimeInstalled: Bool { runtimePresent && ffmpegPresent && ffprobePresent }

    public func jsonData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(self)
    }
}

public enum RuntimeBridge {
    public static func run(arguments: [String], paths: ApplicationPaths = ApplicationPaths()) throws -> Int32 {
        guard let executable = paths.runtimeExecutable,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw RuntimeError.notInstalled
        }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        for key in ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE"] {
            environment.removeValue(forKey: key)
        }
        environment["PYTHONNOUSERSITE"] = "1"
        if let root = paths.bundleURL { environment["ASR_DESKTOP_BUNDLE"] = root.path }
        process.environment = environment
        process.standardInput = FileHandle.standardInput
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus
    }

    public enum RuntimeError: LocalizedError {
        case notInstalled
        public var errorDescription: String? {
            "找不到 App 內建的辨識執行環境，請重新安裝完整的 ASR Desktop。"
        }
    }
}
