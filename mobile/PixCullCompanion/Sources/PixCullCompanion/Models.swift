// P2.1 — JSON response shapes matching the V25 /api/v1 endpoints.
//
// These are deliberately partial — we only decode the fields the
// SwiftUI views actually render. PixCull's responses carry richer
// metadata (per-axis stars, advice text, etc.) that we can wire in
// later versions without breaking back-compat.

import Foundation

public struct APIIndex: Decodable {
    public let schema: String
    public let version: String
    public let server: String
}

public struct UsersResponse: Decodable {
    public let active: String
    public let users: [UserEntry]
}

public struct UserEntry: Decodable, Identifiable {
    public var id: String { user_id }
    public let user_id: String
    public let vertical_count: Int
    public let is_active: Bool
}

public struct UsersActive: Decodable {
    public let ok: Bool
    public let active: String
}

public struct RunListResponse: Decodable {
    public let schema: String
    public let n_runs: Int
    public let runs: [RunEntry]
}

public struct RunEntry: Decodable, Identifiable {
    public var id: String { run_id }
    public let run_id: String
    public let mode: String?
    public let size_bytes: Int?
    public let n_input: Int?
    public let decisions: Decisions?
    public let state: String?
    public let age_seconds: Double?
}

public struct Decisions: Decodable {
    public let keep: Int?
    public let maybe: Int?
    public let cull: Int?
}

public struct RunSummary: Decodable {
    public let schema: String
    public let run_id: String
    public let summary: RunSummaryBody?
    public let face_clusters_n: Int?
    public let locations_n: Int?
    public let links: [String: String]?
}

public struct RunSummaryBody: Decodable {
    public let n_total: Int?
    public let n_keep: Int?
    public let n_maybe: Int?
    public let n_cull: Int?
    public let vertical: String?
}

// P2.1 V0.2 — paginated row list for the photo grid + lightbox.
// Shape mirrors the server's slim ``pixcull.api.v1.rows.v1`` schema:
// just the fields the iOS grid + swipe annotator need.
public struct RowListResponse: Decodable {
    public let schema: String
    public let run_id: String
    public let n_total: Int
    public let offset: Int
    public let limit: Int
    public let rows: [RowEntry]
}

public struct RowEntry: Decodable, Identifiable, Equatable {
    public var id: String { filename }
    public let filename: String
    public let decision: String?
    public let score_final: Double?
    public let scene: String?
    public let cluster_id: Int?
    public let is_burst_peak: Bool?
    public let rubric_human_labeled: Bool?
}

// P2.1 V0.2 — annotation POST response. ``ok`` is True on success;
// ``message`` is set on validation failures (axis name typos etc).
public struct AnnotateResponse: Decodable {
    public let ok: Bool?
    public let message: String?
}

// V0.3 — full single-row response for the rich lightbox.
// Adds advice + rubric stars + GPS + face_clusters on top of the
// slim ``RowEntry`` fields.
public struct RichRowResponse: Decodable {
    public let schema: String
    public let run_id: String
    public let row: RichRow
}

public struct RichRow: Decodable {
    public let filename: String
    public let decision: String?
    public let scene: String?
    public let score_final: Double?
    public let score_sharpness: Double?
    public let score_exposure: Double?
    public let score_aesthetic: Double?
    public let score_composition: Double?
    public let cluster_id: Int?
    public let is_burst_peak: Bool?
    public let rubric_human_labeled: Bool?
    public let reason: String?

    public let advice: Advice?
    public let rubric_stars: [String: Double]?
    public let face_clusters: [Int]?

    public let gps_lat: Double?
    public let gps_lon: Double?
    public let gps_cluster_id: Int?

    public let meta_overall_rationale: String?
    public let meta_confidence: Double?
    public let vlm_overall_rationale: String?
}

public struct Advice: Decodable {
    public let verdict_short: String?
    public let verdict: String?
    public let strengths: [String]?
    public let weaknesses: [String]?
    public let suggestions: [String]?
    public let rationale: String?
}
