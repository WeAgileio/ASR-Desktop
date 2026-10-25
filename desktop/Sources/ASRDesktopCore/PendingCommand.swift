import Foundation

/// Retains the exact payload and request identity until a response is received.
public struct PendingCommand: Sendable {
    public let operation: String
    public let requestID: String
    public let arguments: Data

    public init(_ operation: String, arguments: [String: Any]) throws {
        self.operation = operation
        self.requestID = UUID().uuidString
        self.arguments = try JSONSerialization.data(withJSONObject: arguments, options: [.sortedKeys])
    }

    public func send() throws -> Data {
        let decoded = try JSONSerialization.jsonObject(with: arguments) as? [String: Any] ?? [:]
        return try ControlSocket.request(operation, arguments: decoded, requestID: requestID)
    }
}
