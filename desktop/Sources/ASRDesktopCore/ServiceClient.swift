import Foundation

public enum ServiceClient {
    public static func ensureReady() throws {
        if let data = try? ControlSocket.request("service.status"),
           let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
           value["success"] as? Bool == true { return }
        if ApplicationPaths().isDevelopmentBuild {
            _ = try DevelopmentLauncher.start()
        } else {
            let (_, status) = try AppServiceBridge.run("register")
            guard status == 0 else { throw ControlSocket.ControlError.unavailable }
            for _ in 0..<100 {
                if (try? ControlSocket.request("service.status")) != nil { return }
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
