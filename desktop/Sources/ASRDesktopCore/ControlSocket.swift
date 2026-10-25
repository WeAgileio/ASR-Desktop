import Darwin
import Foundation

public enum ControlSocket {
    public static var path: String {
        let directory = ProcessInfo.processInfo.environment["ASR_DESKTOP_RUN_DIR"] ?? "/private/tmp/asr-desktop-\(getuid())"
        return directory + "/control.sock"
    }

    static func timeoutSeconds(for operation: String) -> Int {
        ["models.verify", "submit", "intake.preview", "jobs.retry"].contains(operation) ? 120 : 3
    }

    public static func request(_ operation: String, arguments: [String: Any] = [:], requestID: String = UUID().uuidString) throws -> Data {
        let directory = URL(fileURLWithPath: path).deletingLastPathComponent().path
        var parentInfo = stat()
        var socketInfo = stat()
        guard Darwin.lstat(directory, &parentInfo) == 0,
              parentInfo.st_uid == getuid(), (parentInfo.st_mode & 0o777) == 0o700,
              (parentInfo.st_mode & S_IFMT) == S_IFDIR,
              Darwin.lstat(path, &socketInfo) == 0, socketInfo.st_uid == getuid(),
              (socketInfo.st_mode & 0o777) == 0o600, (socketInfo.st_mode & S_IFMT) == S_IFSOCK else {
            throw ControlError.unavailable
        }
        let descriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw ControlError.unavailable }
        defer { Darwin.close(descriptor) }
        var timeout = timeval(tv_sec: timeoutSeconds(for: operation), tv_usec: 0)
        var noSignal: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout.size(ofValue: noSignal)))
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let bytes = Array(path.utf8CString).map { UInt8(bitPattern: $0) }
        guard bytes.count <= MemoryLayout.size(ofValue: address.sun_path) else { throw ControlError.invalidResponse }
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes) }
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else { throw ControlError.unavailable }
        var peerUser: uid_t = 0
        var peerGroup: gid_t = 0
        guard getpeereid(descriptor, &peerUser, &peerGroup) == 0, peerUser == getuid() else {
            throw ControlError.unavailable
        }
        let payload = try JSONSerialization.data(withJSONObject: [
            "protocol_version": 1, "id": requestID, "operation": operation, "arguments": arguments,
        ]) + Data([10])
        guard payload.count <= 65536 else { throw ControlError.requestTooLarge }
        try payload.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                let count = Darwin.send(descriptor, buffer.baseAddress!.advanced(by: offset), buffer.count - offset, 0)
                guard count > 0 else { throw ControlError.unavailable }
                offset += count
            }
        }
        var response = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while !response.contains(10) {
            let count = Darwin.recv(descriptor, &buffer, buffer.count, 0)
            guard count > 0 else { throw ControlError.invalidResponse }
            response.append(contentsOf: buffer.prefix(count))
            guard response.count <= 8 * 1024 * 1024 else { throw ControlError.invalidResponse }
        }
        let object = try JSONSerialization.jsonObject(with: response)
        guard let reply = object as? [String: Any], reply["protocol_version"] as? Int == 1,
              reply["id"] as? String == requestID, reply["success"] is Bool else {
            throw ControlError.invalidResponse
        }
        return response
    }

    public enum ControlError: LocalizedError {
        case unavailable, invalidResponse, requestTooLarge
        public var errorDescription: String? {
            switch self {
            case .requestTooLarge: "選取項目超過傳輸上限，請縮小選取範圍。"
            case .unavailable: "本機背景服務尚未連線，請先啟動服務並檢查背景執行權限。"
            case .invalidResponse: "背景服務回應無效，請使用相同版本的 App 與 CLI。"
            }
        }
    }
}
