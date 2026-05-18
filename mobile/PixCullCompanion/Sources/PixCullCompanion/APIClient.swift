// P2.1 — PixCull V25 /api/v1 client.
//
// Minimal async/await HTTP layer with the three things every other
// module needs:
//
//   1. Server URL + API key from @AppStorage (Settings view writes
//      them; this client reads at request time so changes apply
//      without an app restart).
//   2. Standard headers — Content-Type, X-PixCull-API-Key when set.
//   3. JSON decoding into the small set of response structs in
//      Models.swift.
//
// Errors flatten to a single APIError enum so callers can pattern-
// match in a `do/catch`. Non-200 responses come back as
// `.httpStatus(code, body)` for the UI to display "Server returned
// HTTP 401 — check your API key" rather than a network-stack
// abstraction.

import Foundation
import SwiftUI

public enum APIError: Error, LocalizedError {
    case noServerConfigured
    case invalidURL(String)
    case network(Error)
    case httpStatus(Int, String)
    case decodeFailed(Error)

    public var errorDescription: String? {
        switch self {
        case .noServerConfigured:
            return "Server URL is not set. Tap the gear icon to enter one."
        case .invalidURL(let s):
            return "Invalid URL: \(s)"
        case .network(let e):
            return "Network error: \(e.localizedDescription)"
        case .httpStatus(let code, let body):
            return "Server returned HTTP \(code). \(body.prefix(200))"
        case .decodeFailed(let e):
            return "Bad response shape: \(e.localizedDescription)"
        }
    }
}

@MainActor
public final class APIClient: ObservableObject {

    // MARK: Settings (@AppStorage so SwiftUI views see the same value)

    @AppStorage("pixcull_server_url") public var serverURL: String = ""
    @AppStorage("pixcull_api_key")    public var apiKey: String = ""

    // V28.2 — when the user picks a profile via SettingsView, store
    // it locally and send it as X-PixCull-User on every request.
    // PixCull's server reads it ahead of cookies / env.
    @AppStorage("pixcull_active_user") public var activeUser: String = ""

    public init() {}

    // MARK: Request shaping

    private func makeRequest(_ path: String,
                              method: String = "GET",
                              body: Data? = nil) throws -> URLRequest {
        guard !serverURL.isEmpty else {
            throw APIError.noServerConfigured
        }
        // Trim trailing slash so /api/v1/ path concat is clean.
        let base = serverURL.trimmingCharacters(
            in: CharacterSet(charactersIn: "/"))
        let full = base + path
        guard let url = URL(string: full) else {
            throw APIError.invalidURL(full)
        }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = method
        req.addValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty {
            req.addValue(apiKey, forHTTPHeaderField: "X-PixCull-API-Key")
        }
        if !activeUser.isEmpty {
            req.addValue(activeUser, forHTTPHeaderField: "X-PixCull-User")
        }
        if let body = body {
            req.httpBody = body
        }
        return req
    }

    private func runRequest<T: Decodable>(_ req: URLRequest,
                                            as: T.Type) async throws -> T {
        do {
            let (data, response) = try await URLSession.shared.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.network(URLError(.badServerResponse))
            }
            guard (200..<300).contains(http.statusCode) else {
                let body = String(data: data, encoding: .utf8) ?? ""
                throw APIError.httpStatus(http.statusCode, body)
            }
            do {
                return try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw APIError.decodeFailed(error)
            }
        } catch let err as APIError {
            throw err
        } catch {
            throw APIError.network(error)
        }
    }

    // MARK: Endpoints

    public func ping() async throws -> APIIndex {
        let req = try makeRequest("/api/v1/")
        return try await runRequest(req, as: APIIndex.self)
    }

    public func listRuns() async throws -> RunListResponse {
        let req = try makeRequest("/api/v1/runs")
        return try await runRequest(req, as: RunListResponse.self)
    }

    public func runSummary(_ runID: String) async throws -> RunSummary {
        let req = try makeRequest("/api/v1/runs/\(runID)")
        return try await runRequest(req, as: RunSummary.self)
    }

    public func listUsers() async throws -> UsersResponse {
        let req = try makeRequest("/api/v1/users")
        return try await runRequest(req, as: UsersResponse.self)
    }

    public func switchUser(_ uid: String) async throws -> UsersActive {
        let body = try JSONSerialization.data(
            withJSONObject: ["user_id": uid])
        let req = try makeRequest("/api/v1/users/active",
                                   method: "POST", body: body)
        return try await runRequest(req, as: UsersActive.self)
    }

    // P2.1 V0.2 — paginated row list for the photo grid.
    public func rows(_ runID: String,
                       limit: Int = 200,
                       offset: Int = 0) async throws -> RowListResponse {
        let path = "/api/v1/runs/\(runID)/rows?limit=\(limit)&offset=\(offset)"
        let req = try makeRequest(path)
        return try await runRequest(req, as: RowListResponse.self)
    }

    // P2.1 V0.2 — POST a swipe-annotation. Empty axes dict; only
    // the overall keep/maybe/cull label travels. Per-axis rubric
    // annotation stays in the browser /annotate flow.
    public func annotate(runID: String,
                          filename: String,
                          decision: String) async throws -> AnnotateResponse {
        let body = try JSONSerialization.data(withJSONObject: [
            "axes": [:],
            "overall_label": decision,
            "overall_rationale": "iOS swipe (PixCullCompanion V0.2)",
        ])
        // URL-encode the filename for the path segment — phones shoot
        // photos with spaces / non-ASCII in their names.
        let encoded = filename.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed) ?? filename
        let path = "/api/v1/runs/\(runID)/annotate/\(encoded)"
        let req = try makeRequest(path, method: "POST", body: body)
        return try await runRequest(req, as: AnnotateResponse.self)
    }

    // P2.1 V0.2 — URL for a photo's thumbnail. Renders via AsyncImage.
    // ``size`` is the long-side cap; the existing /thumb endpoint
    // honors ?w= for cache-bucket sizing.
    public func thumbURL(runID: String, filename: String,
                           size: Int = 420) -> URL? {
        let base = serverURL.trimmingCharacters(
            in: CharacterSet(charactersIn: "/"))
        let enc = filename.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed) ?? filename
        return URL(string: "\(base)/thumb/\(runID)/\(enc)?w=\(size)")
    }

    public func fullURL(runID: String, filename: String,
                          size: Int = 1600) -> URL? {
        let base = serverURL.trimmingCharacters(
            in: CharacterSet(charactersIn: "/"))
        let enc = filename.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed) ?? filename
        return URL(string: "\(base)/full/\(runID)/\(enc)?w=\(size)")
    }
}
