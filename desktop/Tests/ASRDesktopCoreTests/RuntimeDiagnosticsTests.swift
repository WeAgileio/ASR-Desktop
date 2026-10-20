import ASRDesktopCore
import Foundation
import Testing

@Test func diagnosticDoesNotTrustFilePresenceOrAFalseReadyExit() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let app = root.appendingPathComponent("ASR Desktop.app")
    let paths = ApplicationPaths(executableURL: app.appendingPathComponent("Contents/MacOS/asr-desktop"))
    let executables = [paths.runtimeExecutable!, paths.mediaExecutable("ffmpeg")!, paths.mediaExecutable("ffprobe")!]
    for executable in executables {
        try FileManager.default.createDirectory(at: executable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
    }
    // A valid-looking response with a failing process is not readiness.
    try Data("#!/bin/sh\necho '{\"ready\":true}'\nexit 1\n".utf8).write(to: paths.runtimeExecutable!)
    // write(to:) preserves the existing file's executable mode.
    var result = try RuntimeDiagnostics.run(paths: paths)
    #expect(result.status == 3)
    let response = try JSONSerialization.jsonObject(with: result.data) as? [String: Any]
    #expect(response?["ready"] as? Bool == false)
    // An executable bit on damaged bytes must also fail.
    try Data("damaged runtime bytes".utf8).write(to: paths.runtimeExecutable!)
    result = try RuntimeDiagnostics.run(paths: paths)
    #expect(result.status == 3)
}
