import Foundation

public struct ReleaseHTTPReply: Sendable {
    public let data: Data
    public let status: Int
    public let headers: [String: String]
    public init(data: Data, status: Int = 200, headers: [String: String] = [:]) {
        self.data = data; self.status = status
        self.headers = Dictionary(headers.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { _, last in last })
    }
}

private final class ReleaseRedirectPolicy: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public struct ReleaseClient: Sendable {
    public typealias Transport = @Sendable (URLRequest) async throws -> ReleaseHTTPReply
    public static let endpoint = URL(string: "https://api.github.com/repos/WeAgileio/ASR-Desktop/releases?per_page=100")!
    public let transport: Transport
    public init(transport: @escaping Transport = ReleaseClient.request) { self.transport = transport }

    public static func request(_ request: URLRequest) async throws -> ReleaseHTTPReply {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 30
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        let session = URLSession(configuration: configuration, delegate: ReleaseRedirectPolicy(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw ReleaseCheckError.invalidResponse }
        var data = Data()
        for try await byte in bytes {
            guard data.count < 2 * 1024 * 1024 else { throw ReleaseCheckError.incomplete }
            data.append(byte)
        }
        var headers: [String: String] = [:]
        for (key, value) in http.allHeaderFields { headers[String(describing: key)] = String(describing: value) }
        return ReleaseHTTPReply(data: data, status: http.statusCode, headers: headers)
    }

    public func fetch(now: Date = Date()) async throws -> [DesktopRelease] {
        try await withThrowingTaskGroup(of: [DesktopRelease].self) { group in
            group.addTask { try await pages(now: now) }
            group.addTask {
                try await Task.sleep(for: .seconds(45))
                throw ReleaseCheckError.incomplete
            }
            defer { group.cancelAll() }
            return try await group.next() ?? []
        }
    }
    private func pages(now: Date) async throws -> [DesktopRelease] {
        var next: URL? = Self.endpoint
        var visited = Set<URL>()
        var releases: [DesktopRelease] = []
        var size = 0
        while let url = next {
            try Task.checkCancellation()
            guard visited.count < 10, visited.insert(url).inserted,
                  url.scheme == "https", url.host == "api.github.com", url.port == nil,
                  url.user == nil, url.password == nil, url.fragment == nil,
                  url.path == Self.endpoint.path else { throw ReleaseCheckError.incomplete }
            var request = URLRequest(url: url)
            request.timeoutInterval = 15
            request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
            request.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
            request.setValue("ASR-Desktop-Update-Check", forHTTPHeaderField: "User-Agent")
            let reply = try await transport(request)
            if reply.status == 429 || (reply.status == 403 && (reply.headers["retry-after"] != nil || reply.headers["x-ratelimit-remaining"] == "0")) {
                var until = now.addingTimeInterval(60)
                if let raw = reply.headers["retry-after"] {
                    if let seconds = TimeInterval(raw), seconds.isFinite { until = now.addingTimeInterval(max(1, seconds)) }
                    else {
                        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
                        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
                        if let date = formatter.date(from: raw) { until = max(until, date) }
                    }
                }
                if let raw = reply.headers["x-ratelimit-reset"], let seconds = TimeInterval(raw), seconds.isFinite {
                    until = max(until, Date(timeIntervalSince1970: seconds))
                }
                throw ReleaseCheckError.rateLimited(until)
            }
            guard reply.status == 200 else { throw ReleaseCheckError.http(reply.status) }
            size += reply.data.count
            guard reply.data.count <= 2 * 1024 * 1024, size <= 8 * 1024 * 1024 else { throw ReleaseCheckError.incomplete }
            do { releases += try JSONDecoder().decode([DesktopRelease].self, from: reply.data) }
            catch { throw ReleaseCheckError.invalidResponse }
            next = nil
            if let link = reply.headers["link"] {
                for part in link.split(separator: ",") where part.contains("rel=\"next\"") {
                    guard next == nil, let start = part.firstIndex(of: "<"), let end = part.firstIndex(of: ">"), start < end,
                          let target = URL(string: String(part[part.index(after: start)..<end])) else { throw ReleaseCheckError.invalidResponse }
                    next = target
                }
            }
        }
        return releases
    }
}
