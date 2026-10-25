import Foundation

public enum ServiceClient {
    static func isReady(_ data: Data) -> Bool {
        guard let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              value["success"] as? Bool == true,
              let result = value["result"] as? [String: Any] else { return false }
        return result["state"] as? String == "running" && result["execution_ready"] as? Bool == true
    }

    public static func ensureReady() throws {
        if let data = try? ControlSocket.request("service.status"),
           isReady(data) { return }
        if ApplicationPaths().isDevelopmentBuild {
            guard isReady(try DevelopmentLauncher.start()) else {
                throw ControlSocket.ControlError.unavailable
            }
        } else {
            let (_, status) = try AppServiceBridge.run("register")
            guard status == 0 else { throw ControlSocket.ControlError.unavailable }
            for _ in 0..<100 {
                if let data = try? ControlSocket.request("service.status"), isReady(data) { return }
                Thread.sleep(forTimeInterval: 0.1)
            }
            throw ControlSocket.ControlError.unavailable
        }
    }

    public static func command(_ operation: String, arguments: [String: Any] = [:],
                               requestID: String = UUID().uuidString) throws -> Data {
        try ensureReady()
        return try ControlSocket.request(operation, arguments: arguments, requestID: requestID)
    }
}
