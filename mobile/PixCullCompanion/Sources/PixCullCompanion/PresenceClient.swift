// v0.10-P0-4 — iOS presence + push client.
//
// Mirrors the web's v0.9-P1-2 (presence) + v0.10-P0-1 (push)
// protocols.  Heartbeat every 30 s, poll every 10 s; both
// shut down when the app backgrounds and resume on foreground
// to match Apple's energy-impact guidance.
//
// Wired into a SwiftUI view as an @ObservedObject — the peers
// array drives the toolbar presence pill.

import Foundation
import Combine

// MARK: - Wire types

public struct PresencePeer: Decodable, Identifiable {
    public var id: String { client_id }
    public let client_id: String
    public let display_name: String?
    public let last_viewed_filename: String?
    public let last_action: String?
    public let last_action_filename: String?
    public let last_action_at_ms: Int64?
    public let last_seen_ms: Int64?
}

public struct PresenceListResponse: Decodable {
    public let schema:    String
    public let event_id:  String
    public let run_id:    String?
    public let server_ts: Int64?
    public let peers:     [PresencePeer]
}

public struct PushEditRequest: Encodable {
    public let filename:    String
    public let decision:    String?
    public let rubric_stars: [String: Double]?
    public let cull_reason: String?
    public let client_id:   String?
    public let client_ts_ms: Int64?
    public let edited_by:   String?

    public init(filename: String, decision: String? = nil,
                rubric_stars: [String: Double]? = nil,
                cull_reason: String? = nil,
                client_id: String? = nil,
                client_ts_ms: Int64? = nil,
                edited_by: String? = nil) {
        self.filename = filename
        self.decision = decision
        self.rubric_stars = rubric_stars
        self.cull_reason = cull_reason
        self.client_id = client_id
        self.client_ts_ms = client_ts_ms
        self.edited_by = edited_by
    }
}

public struct PushResponse: Decodable {
    public let ok:        Bool
    public let accepted:  Int
    public let rejected:  Int
    public let server_ts: Int64?
}

// MARK: - Client

@MainActor
public final class PresenceClient: ObservableObject {
    @Published public private(set) var peers: [PresencePeer] = []
    @Published public private(set) var lastSyncTs: Int64 = 0
    @Published public private(set) var offlineQueueDepth: Int = 0

    private let api: APIClient
    private let token: String          // event token from join URL
    private let clientId: String       // persistent per-install
    private var displayName: String

    private var heartbeatTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    private var offlineQueue: [PushEditRequest] = []

    public init(api: APIClient, token: String,
                clientId: String, displayName: String) {
        self.api = api
        self.token = token
        self.clientId = clientId
        self.displayName = displayName
    }

    // MARK: lifecycle
    public func start() {
        stop()  // idempotent
        heartbeatTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.beat(viewing: nil, action: nil, actionFilename: nil)
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
        pollTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.poll()
                try? await Task.sleep(nanoseconds: 10_000_000_000)
            }
        }
    }

    public func stop() {
        heartbeatTask?.cancel(); heartbeatTask = nil
        pollTask?.cancel();     pollTask = nil
    }

    // MARK: heartbeats

    /// Call this when the user opens a photo so peers see the
    /// viewer-position update within the next poll window.
    public func setViewing(_ filename: String?) async {
        await beat(viewing: filename, action: nil, actionFilename: nil)
    }

    /// Call after a local decision change so peers immediately
    /// see "✅ 二摄 标 keep · IMG_001".
    public func markAction(_ action: String, filename: String) async {
        await beat(viewing: nil, action: action, actionFilename: filename)
    }

    private func beat(viewing: String?, action: String?,
                       actionFilename: String?) async {
        struct Body: Encodable {
            let client_id: String
            let display_name: String
            let last_viewed_filename: String?
            let action: String?
            let action_filename: String?
        }
        let body = Body(
            client_id:            clientId,
            display_name:         displayName,
            last_viewed_filename: viewing,
            action:               action,
            action_filename:      actionFilename
        )
        let path = "/sync/event/\(token)/presence"
        // best-effort — drop errors silently, the next beat retries
        _ = try? await api.post(path: path, body: body) as PushResponse?
    }

    private func poll() async {
        let path = "/api/v1/sync/event/\(token)/presence?exclude=\(clientId)"
        guard let resp: PresenceListResponse =
                try? await api.get(path: path) else { return }
        self.peers = resp.peers
        self.lastSyncTs = resp.server_ts ?? Int64(Date().timeIntervalSince1970 * 1000)
    }

    // MARK: push
    /// Push one or more annotation edits to the host.  On network
    /// failure, queues to ``offlineQueue`` and the next visibility-
    /// change or 30 s timer retries.  Matches the web's
    /// _pushEdits semantics.
    public func pushEdits(_ edits: [PushEditRequest]) async -> Bool {
        struct Body: Encodable { let edits: [PushEditRequest] }
        let stamped = edits.map { e in
            PushEditRequest(
                filename: e.filename,
                decision: e.decision,
                rubric_stars: e.rubric_stars,
                cull_reason: e.cull_reason,
                client_id: clientId,
                client_ts_ms: Int64(Date().timeIntervalSince1970 * 1000),
                edited_by: displayName
            )
        }
        let body = Body(edits: stamped)
        do {
            let resp: PushResponse = try await api.post(
                path: "/sync/event/\(token)/push", body: body)
            // On success, flush any offline queue too.
            await flushOfflineQueue()
            return resp.ok
        } catch {
            // Queue offline.  In-memory only on iOS (no IDB); restart
            // loses pending edits.  Background-task wake-up + flush
            // is a future slice.
            offlineQueue.append(contentsOf: stamped)
            offlineQueueDepth = offlineQueue.count
            return false
        }
    }

    public func flushOfflineQueue() async {
        guard !offlineQueue.isEmpty else { return }
        let batch = offlineQueue
        offlineQueue.removeAll()
        offlineQueueDepth = 0
        struct Body: Encodable { let edits: [PushEditRequest] }
        do {
            let resp: PushResponse = try await api.post(
                path: "/sync/event/\(token)/push",
                body: Body(edits: batch))
            if !resp.ok {
                offlineQueue = batch
                offlineQueueDepth = offlineQueue.count
            }
        } catch {
            offlineQueue = batch
            offlineQueueDepth = offlineQueue.count
        }
    }
}
