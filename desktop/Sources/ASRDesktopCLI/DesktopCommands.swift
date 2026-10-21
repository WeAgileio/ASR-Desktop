import ASRDesktopCore
import Darwin
import Foundation

enum DesktopCommands {
    static let help = """
    ASR Desktop — Apple Silicon local transcription
      submit PATH... --output-dir DIR [--recursive] [--wait] [--preview]
        [--model MODEL_ID] [--device auto|cpu|gpu|mps]
        [--formats txt,srt,json] [--script traditional|simplified|original]
        [--language LANGUAGE] [--hotword WORD] [--overwrite]
      jobs list | show ID | watch ID [--cursor N] | cancel ID | retry ID
      queue status | pause | resume
      models list | download ID | verify ID | remove ID
      settings show | set KEY VALUE
      device explain | calibrate PATH [--model MODEL] [--wait]
      service start | status | stop [--force] | unregister
      cli install [--directory DIR]
      diagnose [--json] | --version

    Results use JSON; watch uses NDJSON. --json is accepted by every command.
    --request-id ID makes mutation retries safe. Queue resume starts accepted work.
    Exit: 0 success, 1 job failure/cancel, 2 arguments, 3 prerequisite, 130 Ctrl-C.
    """

    static func run(_ original: [String]) -> Bool {
        guard let family = original.first,
              ["submit", "jobs", "queue", "models", "settings", "service", "device", "cli"].contains(family) else { return false }
        var args = original.filter { $0 != "--json" }
        var requestID = UUID().uuidString
        if let index = args.firstIndex(of: "--request-id") {
            guard index + 1 < args.count else { fail("--request-id requires a value", 2) }
            requestID = args[index + 1]
            args.removeSubrange(index...index + 1)
        }
        do {
            var operation = ""
            var parameters: [String: Any] = [:]
            var wait = false
            switch family {
            case "submit":
                operation = "submit"
                var paths: [String] = [], options: [String: Any] = [:]
                var index = 1
                while index < args.count {
                    let value = args[index]
                    switch value {
                    case "--recursive": parameters["recursive"] = true
                    case "--wait": wait = true
                    case "--preview": operation = "intake.preview"
                    case "--overwrite": options["overwrite"] = true
                    case "--output-dir", "--model", "--device", "--formats", "--script", "--language", "--hotword":
                        guard index + 1 < args.count else { fail("\(value) requires a value", 2) }
                        index += 1
                        let argument = args[index]
                        if value == "--output-dir" { parameters["output_dir"] = URL(fileURLWithPath: (argument as NSString).expandingTildeInPath).standardizedFileURL.path }
                        else if value == "--formats" { options["formats"] = argument.split(separator: ",").map(String.init) }
                        else if value == "--hotword" { options["hotwords"] = (options["hotwords"] as? [String] ?? []) + [argument] }
                        else { options[String(value.dropFirst(2))] = argument }
                    case "--":
                        paths += Array(args.dropFirst(index + 1))
                        index = args.count
                    default:
                        guard !value.hasPrefix("--") else { fail("Unknown option: \(value)", 2) }
                        paths.append(value)
                    }
                    index += 1
                }
                guard !paths.isEmpty, parameters["output_dir"] != nil else { fail("Provide paths and --output-dir", 2) }
                parameters["paths"] = paths.map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath).standardizedFileURL.path }
                parameters["settings"] = options
            case "jobs":
                guard args.count >= 2 else { fail("Choose a jobs command", 2) }
                if args[1] == "watch" {
                    guard args.count == 3 || (args.count == 5 && args[3] == "--cursor" && Int(args[4]) != nil) else { fail("jobs watch ID [--cursor N]", 2) }
                    try observe(args[2], cursor: args.count == 5 ? Int(args[4])! : 0, wait: false)
                    exit(0)
                }
                guard ["list", "show", "cancel", "retry"].contains(args[1]), args.count == (args[1] == "list" ? 2 : 3) else { fail("Invalid jobs command", 2) }
                operation = "jobs." + args[1]
                if args.count == 3 { parameters["id"] = args[2] }
            case "queue", "models", "settings", "device":
                guard args.count >= 2 else { fail("Choose a \(family) command", 2) }
                operation = family + "." + args[1]
                if family == "device", args[1] == "calibrate" {
                    guard args.count >= 3 else { fail("device calibrate PATH [--model MODEL] [--wait]", 2) }
                    parameters["paths"] = [URL(fileURLWithPath: (args[2] as NSString).expandingTildeInPath).standardizedFileURL.path]
                    var index = 3
                    while index < args.count {
                        if args[index] == "--wait" { wait = true }
                        else if args[index] == "--model", index + 1 < args.count {
                            index += 1; parameters["settings"] = ["model": args[index]]
                        } else { fail("Invalid calibration option", 2) }
                        index += 1
                    }
                } else if family == "models" {
                    guard ["list", "download", "verify", "remove"].contains(args[1]), args.count == (args[1] == "list" ? 2 : 3) else { fail("Invalid models command", 2) }
                    if args.count == 3 { parameters["id"] = args[2] }
                } else if family == "settings", args[1] == "set" {
                    guard args.count == 4 else { fail("settings set KEY VALUE", 2) }
                    let value = (try? JSONSerialization.jsonObject(with: Data(args[3].utf8), options: [.fragmentsAllowed])) ?? args[3]
                    parameters["settings"] = [args[2]: value]
                } else {
                    let choices = family == "queue" ? ["status", "pause", "resume"] : (family == "settings" ? ["show"] : ["explain"])
                    guard args.count == 2 && choices.contains(args[1]) else { fail("Invalid \(family) command", 2) }
                }
            case "service":
                guard args.count >= 2 else { fail("Choose a service command", 2) }
                if args[1] == "start", args.count == 2 {
                    try ServiceClient.ensureReady()
                    write(try ControlSocket.request("service.status"))
                    exit(0)
                }
                if args[1] == "unregister", args.count == 2 {
                    let (data, status) = try AppServiceBridge.run("unregister")
                    write(data)
                    exit(status)
                }
                guard ["status", "stop"].contains(args[1]), args.count == 2 || (args.count == 3 && args[1] == "stop" && args[2] == "--force") else { fail("Invalid service command", 2) }
                let data = try ControlSocket.request("service." + args[1], arguments: args.count == 3 ? ["force": true] : [:], requestID: requestID)
                write(data)
                exit(exitCode(data))
            case "cli":
                guard args.count == 2 || (args.count == 4 && args[2] == "--directory"), args[1] == "install" else { fail("cli install [--directory DIR]", 2) }
                let directory = args.count == 4 ? URL(fileURLWithPath: args[3]) : FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin")
                let link = try CommandLink.install(directory: directory)
                write(try JSONSerialization.data(withJSONObject: ["success": true, "path": link.path]))
                exit(0)
            default: return false
            }
            let data = try ServiceClient.command(operation, arguments: parameters, requestID: requestID)
            write(data)
            let code = exitCode(data)
            if code != 0 { exit(code) }
            if wait, let reply = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let result = reply["result"] as? [String: Any], let identifier = result["id"] as? String {
                try observe(identifier, cursor: 0, wait: true)
            }
            exit(0)
        } catch { fail(error.localizedDescription, 3) }
    }

    static func observe(_ identifier: String, cursor initialCursor: Int, wait: Bool) throws {
        signal(SIGINT) { _ in _exit(130) }
        var cursor = initialCursor
        while true {
            let data = try ServiceClient.command("jobs.show", arguments: ["id": identifier])
            guard exitCode(data) == 0,
                  let reply = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let result = reply["result"] as? [String: Any] else { write(data); exit(3) }
            let jobs = result["jobs"] as? [[String: Any]] ?? [result]
            let identifiers = Set(jobs.compactMap { $0["id"] as? String })
            let eventsData = try ServiceClient.command("events.poll", arguments: ["cursor": cursor])
            if let envelope = try JSONSerialization.jsonObject(with: eventsData) as? [String: Any],
               let page = envelope["result"] as? [String: Any] {
                cursor = page["cursor"] as? Int ?? cursor
                if page["reset"] as? Bool == true { write(eventsData) }
                for event in page["events"] as? [[String: Any]] ?? [] {
                    let details = event["details"] as? [String: Any]
                    if identifiers.contains(event["entity_id"] as? String ?? "") || details?["batch_id"] as? String == identifier {
                        write(try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys]))
                    }
                }
            }
            let counts = result["counts"] as? [String: Int]
            let states = counts?.filter { $0.value > 0 }.map(\.key) ?? jobs.compactMap { $0["state"] as? String }
            if !states.isEmpty && states.allSatisfy({ ["completed", "failed", "cancelled"].contains($0) }) {
                write(data)
                exit(states.allSatisfy { $0 == "completed" } ? 0 : 1)
            }
            if wait && states.contains(where: { ["blocked", "interrupted"].contains($0) }) { write(data); exit(3) }
            if wait {
                let queue = try ServiceClient.command("queue.status")
                if let object = try JSONSerialization.jsonObject(with: queue) as? [String: Any],
                   let result = object["result"] as? [String: Any], result["paused"] as? Bool == true,
                   !states.contains("running") { write(data); exit(3) }
            }
            Thread.sleep(forTimeInterval: 0.5)
        }
    }

    static func write(_ data: Data) {
        FileHandle.standardOutput.write(data)
        if data.last != 10 { FileHandle.standardOutput.write(Data([10])) }
    }
    static func exitCode(_ data: Data) -> Int32 {
        guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return 3 }
        if value["success"] as? Bool == true { return 0 }
        let error = value["error"] as? [String: Any]
        return ["invalid_arguments", "invalid_settings", "invalid_request_id", "request_id_conflict", "not_found"].contains(error?["code"] as? String ?? "") ? 2 : 3
    }
    static func fail(_ message: String, _ code: Int32) -> Never {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(code)
    }
}
