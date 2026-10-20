import ASRDesktopCore
import Foundation
import Testing

@Test func commandLinkIsIdempotentAndNeverOverwritesAnotherCommand() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let contents = root.appendingPathComponent("ASR Desktop.app/Contents/MacOS")
    try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
    let paths = ApplicationPaths(executableURL: contents.appendingPathComponent("ASRDesktopApp"))
    let directory = root.appendingPathComponent("bin")
    let installed = try CommandLink.install(directory: directory, paths: paths)
    #expect(try FileManager.default.destinationOfSymbolicLink(atPath: installed.path) == contents.appendingPathComponent("asr-desktop").path)
    #expect(try CommandLink.install(directory: directory, paths: paths) == installed)
    try FileManager.default.removeItem(at: installed)
    try Data("existing command".utf8).write(to: installed)
    #expect(throws: NSError.self) { _ = try CommandLink.install(directory: directory, paths: paths) }
    #expect(try String(contentsOf: installed, encoding: .utf8) == "existing command")
}
