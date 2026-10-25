import Foundation
import Testing
@testable import ASRDesktopCore

@Test func retryIdentityAndTimeout() throws {
    let command = try PendingCommand("jobs.retry", arguments: ["selector": ["ids": ["job-1"]]])
    let resend = command
    #expect(resend.requestID == command.requestID)
    #expect(resend.arguments == command.arguments)
    #expect(try PendingCommand("jobs.retry", arguments: [:]).requestID != command.requestID)
    #expect(ControlSocket.timeoutSeconds(for: "jobs.retry") == 120)
    #expect(ControlSocket.timeoutSeconds(for: "jobs.list") == 3)
}
