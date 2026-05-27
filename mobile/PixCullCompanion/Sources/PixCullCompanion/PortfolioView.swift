// v0.10-P0-4 — iOS Companion portfolio (作品集) share view.
//
// SwiftUI rebuild of the web v0.9-P0-5 /share/<token> page:
// brand bar + serif hero title + 3 keynum tiles + chapter grid
// of cards.  Sized to play well on both iPhone portrait and
// iPad landscape via adaptive columns.

import SwiftUI

// MARK: - Wire types (mirrors the server's share payload)

public struct PortfolioMeta: Decodable {
    public let photographer: String?
    public let client:       String?
    public let event:        String?
    public let event_date:   String?
    public let contact:      String?
    public let n_total:      Int?
    public let n_keeps:      Int?
    public let ratio:        Double?
    public let scenes:       [String]?
}

public struct PortfolioRow: Decodable, Identifiable {
    public var id: String { filename }
    public let filename:       String
    public let score:          Double?
    public let scene:          String?
    public let wedding_moment: String?
    public let chapter:        String?
}

public struct PortfolioResponse: Decodable {
    public let meta: PortfolioMeta
    public let rows: [PortfolioRow]
}

// MARK: - View

public struct PortfolioView: View {
    public let runID:    String
    public let api:      APIClient
    @State private var resp: PortfolioResponse?
    @State private var loadError: String?
    @Environment(\.dismiss) private var dismiss

    public init(runID: String, api: APIClient) {
        self.runID = runID
        self.api = api
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                brandBar
                hero
                keynums
                if let r = resp {
                    chapters(rows: r.rows)
                } else if let err = loadError {
                    Text(err).foregroundColor(.red).padding()
                } else {
                    ProgressView().padding()
                }
                footer
            }
            .padding(.horizontal, 20)
        }
        .background(Color(.systemBackground))
        .task { await load() }
    }

    private func load() async {
        do {
            // Endpoint is the same one /share/<run>/<token> reads —
            // here we hit a JSON variant `/api/v1/runs/<run>/portfolio`
            // that the v0.10-P0-4 server-side complement exposes.
            let r: PortfolioResponse = try await api.get(
                path: "/api/v1/runs/\(runID)/portfolio")
            self.resp = r
        } catch {
            self.loadError = error.localizedDescription
        }
    }

    // MARK: subviews
    private var brandBar: some View {
        HStack(spacing: 10) {
            // Same SVG ideogram in tiny form — 4 muted dots + 1 brand-grad
            ZStack {
                HStack(spacing: 4) {
                    Circle().fill(Color.gray.opacity(0.5)).frame(width: 5)
                    Circle().fill(Color.gray.opacity(0.6)).frame(width: 5)
                    Circle().fill(Color.gray.opacity(0.7)).frame(width: 5)
                    Circle().fill(Color.gray.opacity(0.6)).frame(width: 5)
                    Circle().fill(Brand.gradient).frame(width: 12)
                }
            }
            Text("Pix").font(.system(size: 16, weight: .heavy))
                + Text("Cull").font(.system(size: 16, weight: .heavy)).foregroundStyle(Brand.gradient)
            Spacer()
            Text("摄影作品交付").font(.caption).foregroundColor(.secondary)
        }
        .padding(.vertical, 12)
        .overlay(
            Rectangle()
                .fill(Color(.separator))
                .frame(height: 0.5),
            alignment: .bottom
        )
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let meta = resp?.meta {
                Text((meta.photographer ?? "—") + " · 摄影作品交付")
                    .font(.caption)
                    .tracking(1.6)
                    .foregroundColor(.secondary)
                Text(meta.event ?? "PixCull Delivery Report")
                    .font(.system(size: 36, weight: .semibold, design: .serif))
                    .foregroundStyle(Brand.gradient)
                    .lineLimit(2)
                Text(meta.client ?? "—")
                    .font(.title3.weight(.medium))
                Text(meta.event_date ?? "")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.top, 14)
    }

    private var keynums: some View {
        HStack(spacing: 16) {
            keynum(value: "\(resp?.meta.n_total ?? 0)",
                    label: "提交张数")
            keynum(value: "\(resp?.meta.n_keeps ?? 0)",
                    label: "入选张数")
            keynum(value: "\(Int(((resp?.meta.ratio ?? 0) * 100).rounded()))%",
                    label: "入选率")
        }
        .padding(.vertical, 16)
        .overlay(
            Rectangle().fill(Color(.separator)).frame(height: 0.5),
            alignment: .top
        )
    }

    private func keynum(value: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.system(size: 28, weight: .semibold, design: .serif))
                .brandGradient()
            Text(label)
                .font(.caption2)
                .tracking(1.2)
                .foregroundColor(.secondary)
                .textCase(.uppercase)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func chapters(rows: [PortfolioRow]) -> some View {
        let grouped = Dictionary(grouping: rows, by: { $0.chapter ?? "其他" })
        VStack(alignment: .leading, spacing: 24) {
            ForEach(grouped.keys.sorted(), id: \.self) { chap in
                VStack(alignment: .leading, spacing: 10) {
                    Text(chap)
                        .font(.system(.title2, design: .serif).weight(.semibold))
                    let chRows = grouped[chap] ?? []
                    LazyVGrid(columns: [
                        GridItem(.adaptive(minimum: 140), spacing: 8),
                    ], spacing: 8) {
                        ForEach(chRows) { row in
                            portfolioCard(row: row)
                        }
                    }
                }
            }
        }
    }

    private func portfolioCard(row: PortfolioRow) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let url = api.thumbURL(runID: runID, filename: row.filename, size: 420) {
                AsyncImage(url: url) { img in
                    img.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Color.gray.opacity(0.2)
                }
                .frame(height: 110)
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            HStack(spacing: 6) {
                RadialProgress(score: row.score).frame(width: 16, height: 16)
                Text(String(format: "%.2f", row.score ?? 0)).font(.caption2).brandGradient()
                Spacer()
            }
            Text(row.filename)
                .font(.system(.caption2, design: .monospaced))
                .lineLimit(1).truncationMode(.middle)
                .foregroundColor(.secondary)
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider()
            Text(resp?.meta.photographer ?? "—")
                .font(.system(.body, design: .serif).weight(.semibold))
            if let contact = resp?.meta.contact, !contact.isEmpty {
                Text(contact).font(.caption).foregroundColor(.secondary)
            }
            Text("由 PixCull 本地生成 · 照片永远不出本机")
                .font(.caption2)
                .foregroundColor(.secondary)
                .padding(.top, 4)
        }
        .padding(.vertical, 24)
    }
}
