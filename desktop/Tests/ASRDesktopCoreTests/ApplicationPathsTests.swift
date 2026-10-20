import ASRDesktopCore
import Foundation
import Testing

@Test func bundlePathsPreserveSpacesAndIgnoreWorkingDirectory() {
    let paths = ApplicationPaths(
        executableURL: URL(fileURLWithPath: "/tmp/Some Folder/ASR Desktop.app/Contents/MacOS/asr-desktop"),
        homeDirectory: URL(fileURLWithPath: "/tmp/Test User"))
    #expect(paths.bundleURL?.path == "/tmp/Some Folder/ASR Desktop.app")
    #expect(paths.runtimeExecutable?.path == "/tmp/Some Folder/ASR Desktop.app/Contents/Resources/runtime/asr-desktop-runtime/asr-desktop-runtime")
    #expect(paths.dataDirectory.path == "/tmp/Test User/Library/Application Support/ASR Desktop")
    #expect(paths.mediaExecutable("../other") == nil)
}

@Test func unbundledExecutableDoesNotUseSystemDependencies() {
    let paths = ApplicationPaths(executableURL: URL(fileURLWithPath: "/tmp/asr-desktop"))
    #expect(paths.bundleURL == nil)
    #expect(paths.runtimeExecutable == nil)
    #expect(!paths.diagnostic.runtimeInstalled)
    #expect(!paths.isDevelopmentBuild)
}

@Test func developmentLaunchRequiresExplicitBuildFlag() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let contents = root.appendingPathComponent("ASR Desktop.app/Contents")
    try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let paths = ApplicationPaths(executableURL: contents.appendingPathComponent("MacOS/asr-desktop"))
    #expect(!paths.isDevelopmentBuild)
    for enabled in [true, false] {
        let data = try PropertyListSerialization.data(fromPropertyList: ["ASRDesktopDevelopmentMode": enabled],
                                                     format: .xml, options: 0)
        try data.write(to: contents.appendingPathComponent("Info.plist"))
        #expect(paths.isDevelopmentBuild == enabled)
    }
    #expect(throws: ControlSocket.ControlError.self) {
        _ = try DevelopmentLauncher.start(paths: paths)
    }
}
