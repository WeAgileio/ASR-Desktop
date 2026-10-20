import ASRDesktopCore
import Foundation
import Darwin

let arguments = Array(CommandLine.arguments.dropFirst())
if arguments == ["--serve"] && ProcessInfo.processInfo.environment["ASR_DESKTOP_SERVICE_MODE"] == "development" {
    _ = setsid()
    signal(SIGHUP, SIG_IGN)
}
if arguments == ["--help"] {
    print("ASRDesktopHelper --diagnose | <runtime arguments>")
    exit(0)
}
do {
    exit(try RuntimeBridge.run(arguments: arguments))
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(3)
}
