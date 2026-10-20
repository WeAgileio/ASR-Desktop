import Foundation

public enum CommandLink {
    public static func install(directory: URL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin"),
                               paths: ApplicationPaths = ApplicationPaths()) throws -> URL {
        guard let app = paths.bundleURL else { throw RuntimeBridge.RuntimeError.notInstalled }
        let executable = app.appendingPathComponent("Contents/MacOS/asr-desktop").path
        let link = directory.appendingPathComponent("asr-desktop")
        if let existing = try? FileManager.default.destinationOfSymbolicLink(atPath: link.path), existing == executable { return link }
        if FileManager.default.fileExists(atPath: link.path) || (try? FileManager.default.destinationOfSymbolicLink(atPath: link.path)) != nil {
            throw NSError(domain: "ASRDesktop", code: 3, userInfo: [NSLocalizedDescriptionKey: "同名命令已存在，不會覆寫：\(link.path)"])
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(atPath: link.path, withDestinationPath: executable)
        return link
    }
}
