import ASRDesktopCore
import Foundation

let arguments = Array(CommandLine.arguments.dropFirst())
if DesktopCommands.run(arguments) { exit(0) }
if arguments.isEmpty || arguments == ["--help"] || arguments == ["help"] {
    print(DesktopCommands.help)
    exit(0)
}
if arguments == ["--version"] {
    print(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development")
    exit(0)
}
if arguments == ["diagnose"] || arguments == ["diagnose", "--json"] {
    do {
        let result = try RuntimeDiagnostics.run()
        FileHandle.standardOutput.write(result.data)
        exit(result.status)
    } catch {
        FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
        exit(3)
    }
}
FileHandle.standardError.write(Data("Unknown command. Run asr-desktop --help.\n".utf8))
exit(2)
