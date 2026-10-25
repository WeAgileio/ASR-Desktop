@testable import ASRDesktopCore
import Foundation
import Testing

@Test func serviceReadinessRequiresRunningExecution() throws {
    for (state, executionReady, expected) in [
        ("running", true, true), ("running", false, false),
        ("stopping", true, false), ("stopping", false, false)
    ] {
        let data = try JSONSerialization.data(withJSONObject: [
            "success": true, "result": ["state": state, "execution_ready": executionReady]
        ])
        #expect(ServiceClient.isReady(data) == expected)
    }
}

@Test func serviceReadinessRejectsErrorsAndIncompleteResponses() throws {
    for response: [String: Any] in [
        ["success": false, "error": ["code": "protocol_mismatch"]],
        ["success": true],
        ["success": true, "result": ["state": "running"]],
        ["success": true, "result": ["execution_ready": true]],
        ["success": true, "result": ["state": "running", "execution_ready": "true"]]
    ] {
        #expect(!ServiceClient.isReady(try JSONSerialization.data(withJSONObject: response)))
    }
    #expect(!ServiceClient.isReady(Data("damaged response".utf8)))
}
