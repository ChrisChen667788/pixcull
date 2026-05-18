// P2.1 — SwiftUI views: settings, run list, run detail, photo grid,
// embedded browser.
//
// V0.1 scope (shipped): read-only review of runs the Mac/NAS has
// already analyzed + embedded browser fallback.
//
// V0.2 scope (this revision): native photo grid + per-photo swipe
// gestures. Tapping a card opens a full-screen lightbox; swipe up
// = keep, down = cull, left/right = prev/next photo. Annotations
// POST to /api/v1/runs/<id>/annotate/<filename> and update the
// local row state immediately so the grid reflects changes on
// dismiss. Decisions are persisted server-side via the same
// annotation.jsonl append-only file the V2.0 browser flow uses,
// so labels survive across iOS / browser / Lr-write-back paths.

import SwiftUI
#if canImport(WebKit)
import WebKit
#endif

// MARK: — Root

public struct ContentView: View {
    @StateObject private var api = APIClient()
    @State private var showingSettings = false

    public init() {}

    public var body: some View {
        NavigationStack {
            RunListView()
                .environmentObject(api)
                .navigationTitle("PixCull")
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button {
                            showingSettings = true
                        } label: {
                            Image(systemName: "gearshape")
                        }
                        .accessibilityLabel("Settings")
                    }
                }
                .sheet(isPresented: $showingSettings) {
                    SettingsView()
                        .environmentObject(api)
                }
        }
    }
}

// MARK: — Run list (GET /api/v1/runs)

public struct RunListView: View {
    @EnvironmentObject var api: APIClient
    @State private var runs: [RunEntry] = []
    @State private var loading = true
    @State private var errorMessage: String? = nil

    public var body: some View {
        Group {
            if loading {
                ProgressView("Loading runs…")
            } else if let err = errorMessage {
                VStack(spacing: 16) {
                    Image(systemName: "exclamationmark.icloud.fill")
                        .font(.largeTitle)
                        .foregroundColor(.orange)
                    Text(err)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                    Button("Retry") { Task { await load() } }
                        .buttonStyle(.bordered)
                }
            } else if runs.isEmpty {
                VStack(spacing: 16) {
                    Image(systemName: "tray")
                        .font(.largeTitle)
                        .foregroundColor(.secondary)
                    Text("No runs yet. Trigger a scan from the Mac.")
                        .foregroundColor(.secondary)
                }
            } else {
                List(runs) { run in
                    NavigationLink {
                        RunDetailView(runID: run.run_id)
                            .environmentObject(api)
                    } label: {
                        RunRow(run: run)
                    }
                }
                .refreshable { await load() }
            }
        }
        .task { await load() }
    }

    private func load() async {
        loading = true; errorMessage = nil
        do {
            let resp = try await api.listRuns()
            runs = resp.runs
        } catch {
            errorMessage = (error as? APIError)?.localizedDescription
                ?? error.localizedDescription
        }
        loading = false
    }
}

struct RunRow: View {
    let run: RunEntry
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(run.run_id).font(.system(.body, design: .monospaced))
                Spacer()
                if let mode = run.mode {
                    Text(mode)
                        .font(.caption2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.15))
                        .cornerRadius(4)
                }
            }
            if let d = run.decisions {
                HStack(spacing: 8) {
                    decisionPill("keep", count: d.keep, color: .green)
                    decisionPill("maybe", count: d.maybe, color: .yellow)
                    decisionPill("cull", count: d.cull, color: .red)
                    Spacer()
                    if let n = run.n_input {
                        Text("\(n) photos").font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func decisionPill(_ label: String, count: Int?,
                                color: Color) -> some View {
        Group {
            if let n = count, n > 0 {
                Text("\(label) \(n)")
                    .font(.caption2)
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(color.opacity(0.18))
                    .foregroundColor(color)
                    .cornerRadius(3)
            }
        }
    }
}

// MARK: — Run detail (GET /api/v1/runs/<id>)

public struct RunDetailView: View {
    let runID: String
    @EnvironmentObject var api: APIClient
    @State private var summary: RunSummary?
    @State private var loading = true
    @State private var errorMessage: String? = nil
    @State private var showBrowser = false

    public var body: some View {
        Group {
            if loading {
                ProgressView()
            } else if let err = errorMessage {
                Text(err).foregroundColor(.red).padding()
            } else if let s = summary {
                List {
                    Section("Summary") {
                        LabeledContent("Run ID", value: s.run_id)
                            .textSelection(.enabled)
                        if let body = s.summary {
                            if let t = body.n_total {
                                LabeledContent("Total",
                                                value: "\(t)")
                            }
                            if let k = body.n_keep {
                                LabeledContent("Keep", value: "\(k)")
                            }
                            if let m = body.n_maybe {
                                LabeledContent("Maybe", value: "\(m)")
                            }
                            if let c = body.n_cull {
                                LabeledContent("Cull", value: "\(c)")
                            }
                            if let v = body.vertical {
                                LabeledContent("Vertical", value: v)
                            }
                        }
                        if let n = s.face_clusters_n, n > 0 {
                            LabeledContent("Face clusters", value: "\(n)")
                        }
                        if let n = s.locations_n, n > 0 {
                            LabeledContent("Location clusters",
                                            value: "\(n)")
                        }
                    }
                    Section {
                        // P2.1 V0.2 — native photo grid + swipe annotator
                        NavigationLink {
                            PhotoGridView(runID: runID)
                                .environmentObject(api)
                        } label: {
                            Label("Browse photos (native)",
                                   systemImage: "photo.on.rectangle.angled")
                        }
                        Button("Open full results page (web)") {
                            showBrowser = true
                        }
                    }
                }
            }
        }
        .navigationTitle(runID)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .sheet(isPresented: $showBrowser) {
            if let url = browserURL() {
                EmbeddedBrowser(url: url)
            }
        }
    }

    private func load() async {
        loading = true; errorMessage = nil
        do {
            summary = try await api.runSummary(runID)
        } catch {
            errorMessage = (error as? APIError)?.localizedDescription
                ?? error.localizedDescription
        }
        loading = false
    }

    private func browserURL() -> URL? {
        let base = api.serverURL.trimmingCharacters(
            in: CharacterSet(charactersIn: "/"))
        return URL(string: "\(base)/results/\(runID)")
    }
}

// MARK: — Settings

public struct SettingsView: View {
    @EnvironmentObject var api: APIClient
    @State private var pingStatus: String = ""
    @State private var pinging = false
    @State private var availableUsers: [UserEntry] = []

    public var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("Server URL",
                               text: $api.serverURL,
                               prompt: Text("http://192.168.1.42:8770"))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    SecureField("API Key (optional)", text: $api.apiKey)
                    Button(pinging ? "Pinging…" : "Test connection") {
                        Task { await ping() }
                    }
                    .disabled(pinging || api.serverURL.isEmpty)
                    if !pingStatus.isEmpty {
                        Text(pingStatus)
                            .font(.caption)
                            .foregroundColor(pingStatus.hasPrefix("✓")
                                              ? .green : .red)
                    }
                }
                Section("User profile (V28)") {
                    TextField("Active user",
                               text: $api.activeUser,
                               prompt: Text("default"))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Sent as X-PixCull-User on every request. Leave blank to use the Mac's PIXCULL_USER env default.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    if !availableUsers.isEmpty {
                        ForEach(availableUsers) { u in
                            Button {
                                api.activeUser = u.user_id
                            } label: {
                                HStack {
                                    Text(u.user_id)
                                    Spacer()
                                    Text("\(u.vertical_count) verticals")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                    if api.activeUser == u.user_id
                                        || (api.activeUser.isEmpty && u.is_active) {
                                        Image(systemName: "checkmark")
                                            .foregroundColor(.green)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .task { await loadUsers() }
        }
    }

    private func ping() async {
        pinging = true
        do {
            let info = try await api.ping()
            pingStatus = "✓ Connected to \(info.server) (\(info.version))"
        } catch {
            pingStatus = "✗ \((error as? APIError)?.localizedDescription ?? error.localizedDescription)"
        }
        pinging = false
    }

    private func loadUsers() async {
        do {
            let resp = try await api.listUsers()
            availableUsers = resp.users
        } catch {
            // Silent — Settings is still usable without user list
        }
    }
}

// MARK: — Embedded browser (WKWebView)

#if canImport(WebKit)
struct EmbeddedBrowser: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let v = WKWebView()
        v.load(URLRequest(url: url))
        return v
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {
        // No-op — URL is set on creation; we don't reload on state change.
    }
}
#else
struct EmbeddedBrowser: View {
    let url: URL
    var body: some View {
        Text("WKWebView unavailable on this platform.")
    }
}
#endif


// MARK: — P2.1 V0.2 native photo grid + swipe-to-annotate

/// Native LazyVGrid + AsyncImage thumbnail loader. Tapping any card
/// opens the swipe-to-annotate lightbox.
public struct PhotoGridView: View {
    let runID: String
    @EnvironmentObject var api: APIClient
    @State private var rows: [RowEntry] = []
    @State private var loading = true
    @State private var errorMessage: String? = nil
    @State private var openIndex: Int? = nil

    // Three-column grid scales well from iPhone SE to iPad Mini.
    // Wider iPads benefit from 4 columns but that's V0.2.1.
    private let columns = Array(repeating: GridItem(.flexible(),
                                                       spacing: 2),
                                 count: 3)

    public var body: some View {
        Group {
            if loading {
                ProgressView("Loading photos…")
            } else if let err = errorMessage {
                Text(err).foregroundColor(.red).padding()
            } else if rows.isEmpty {
                Text("No photos in this run.")
                    .foregroundColor(.secondary)
            } else {
                ScrollView {
                    LazyVGrid(columns: columns, spacing: 2) {
                        ForEach(Array(rows.enumerated()), id: \.element.id) {
                            (idx, row) in
                            PhotoCard(row: row, runID: runID)
                                .onTapGesture { openIndex = idx }
                        }
                    }
                    .padding(.horizontal, 2)
                }
            }
        }
        .navigationTitle("\(rows.count) photos")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .fullScreenCover(item: Binding(
            get: { openIndex.map { IndexHolder(value: $0) } },
            set: { openIndex = $0?.value }
        )) { holder in
            PhotoLightboxView(
                runID: runID,
                rows: $rows,
                index: holder.value,
                onClose: { openIndex = nil }
            ).environmentObject(api)
        }
    }

    private func load() async {
        loading = true; errorMessage = nil
        do {
            let resp = try await api.rows(runID, limit: 1000, offset: 0)
            rows = resp.rows
        } catch {
            errorMessage = (error as? APIError)?.localizedDescription
                ?? error.localizedDescription
        }
        loading = false
    }
}

// Identifiable wrapper for the fullScreenCover item binding —
// SwiftUI's `item: Binding<T?>` requires T: Identifiable, and a
// bare Int doesn't qualify.
private struct IndexHolder: Identifiable {
    let value: Int
    var id: Int { value }
}

/// A single thumbnail card with decision badge + score.
struct PhotoCard: View {
    let row: RowEntry
    let runID: String
    @EnvironmentObject var api: APIClient

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            if let url = api.thumbURL(runID: runID, filename: row.filename) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle().fill(Color.gray.opacity(0.2))
                    case .success(let img):
                        img.resizable().scaledToFill()
                    case .failure:
                        Rectangle().fill(Color.red.opacity(0.1))
                            .overlay(
                                Image(systemName: "photo")
                                    .foregroundColor(.secondary)
                            )
                    @unknown default:
                        Rectangle().fill(Color.gray.opacity(0.2))
                    }
                }
                .frame(maxWidth: .infinity)
                .aspectRatio(1, contentMode: .fill)
                .clipped()
            }
            // Decision tint stripe at the bottom — visible at a
            // glance while scrolling.
            VStack(alignment: .leading, spacing: 0) {
                Spacer()
                HStack(spacing: 4) {
                    decisionDot
                    if let s = row.score_final {
                        Text(String(format: "%.2f", s))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundColor(.white)
                    }
                    if row.is_burst_peak == true {
                        Text("🏆")
                            .font(.system(size: 9))
                    }
                    if row.rubric_human_labeled == true {
                        Text("✓")
                            .font(.system(size: 9))
                            .foregroundColor(.green)
                    }
                    Spacer()
                }
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .background(Color.black.opacity(0.5))
            }
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var decisionDot: some View {
        let color: Color = {
            switch row.decision {
            case "keep":  return .green
            case "maybe": return .yellow
            case "cull":  return .red
            default:      return .gray
            }
        }()
        Circle().fill(color)
            .frame(width: 8, height: 8)
    }
}

/// Full-screen lightbox with horizontal swipe between photos and
/// vertical swipe to annotate (up = keep, down = cull). Updates
/// the row's decision in-place via `rows` binding so the grid
/// reflects changes when the lightbox is dismissed.
public struct PhotoLightboxView: View {
    let runID: String
    @Binding var rows: [RowEntry]
    @State var index: Int
    let onClose: () -> Void

    @EnvironmentObject var api: APIClient
    @State private var dragOffset: CGSize = .zero
    @State private var savingDecision: String? = nil
    @State private var lastError: String? = nil

    private let swipeThreshold: CGFloat = 80

    public var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if index >= 0 && index < rows.count {
                let row = rows[index]
                VStack(spacing: 0) {
                    // Top bar
                    HStack {
                        Button(action: onClose) {
                            Image(systemName: "xmark.circle.fill")
                                .font(.title2)
                                .foregroundColor(.white.opacity(0.8))
                        }
                        Spacer()
                        Text("\(index + 1) / \(rows.count)")
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.7))
                        Spacer()
                        Text(row.filename)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundColor(.white.opacity(0.7))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    .padding()

                    Spacer()

                    // Image with swipe gestures
                    if let url = api.fullURL(runID: runID,
                                              filename: row.filename) {
                        AsyncImage(url: url) { phase in
                            switch phase {
                            case .empty:
                                ProgressView().tint(.white)
                            case .success(let img):
                                img.resizable().scaledToFit()
                            case .failure:
                                VStack {
                                    Image(systemName: "photo")
                                        .font(.largeTitle)
                                    Text("Failed to load")
                                        .font(.caption)
                                }
                                .foregroundColor(.white.opacity(0.6))
                            @unknown default:
                                EmptyView()
                            }
                        }
                        .offset(dragOffset)
                        .gesture(makeDragGesture())
                    }

                    Spacer()

                    // Bottom — decision indicator + swipe hints
                    bottomBar(for: row)
                }
                // Visual decision overlay during drag — color
                // intensifies as the user passes the threshold.
                .overlay(decisionHint, alignment: .center)
            }
        }
    }

    @ViewBuilder
    private func bottomBar(for row: RowEntry) -> some View {
        VStack(spacing: 8) {
            HStack(spacing: 12) {
                decisionPill("keep", color: .green, current: row.decision)
                decisionPill("maybe", color: .yellow, current: row.decision)
                decisionPill("cull", color: .red, current: row.decision)
            }
            if let err = lastError {
                Text(err).font(.caption2).foregroundColor(.red)
            } else if let d = savingDecision {
                Text("Saving \(d)…").font(.caption2)
                    .foregroundColor(.white.opacity(0.6))
            } else {
                Text("← → 翻页 · ↑ keep · ↓ cull · 点 → maybe")
                    .font(.caption2)
                    .foregroundColor(.white.opacity(0.4))
            }
        }
        .padding(.bottom, 24)
    }

    private func decisionPill(_ label: String, color: Color,
                                current: String?) -> some View {
        let active = current == label
        return Button {
            Task { await annotate(label) }
        } label: {
            Text(label.uppercased())
                .font(.caption.bold())
                .padding(.horizontal, 16).padding(.vertical, 6)
                .background(active ? color : Color.clear)
                .foregroundColor(active ? .black : color)
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(color, lineWidth: 1.5)
                )
        }
    }

    @ViewBuilder
    private var decisionHint: some View {
        let dx = dragOffset.width
        let dy = dragOffset.height
        if abs(dx) > swipeThreshold || abs(dy) > swipeThreshold {
            let label: String
            let color: Color
            if dx > swipeThreshold {
                label = "→ NEXT"; color = .blue
            } else if dx < -swipeThreshold {
                label = "← PREV"; color = .blue
            } else if dy < -swipeThreshold {
                label = "↑ KEEP"; color = .green
            } else {
                label = "↓ CULL"; color = .red
            }
            Text(label)
                .font(.system(size: 56, weight: .black))
                .foregroundColor(color)
                .opacity(0.6)
        }
    }

    private func makeDragGesture() -> some Gesture {
        DragGesture()
            .onChanged { value in
                dragOffset = value.translation
            }
            .onEnded { value in
                let dx = value.translation.width
                let dy = value.translation.height
                if dx > swipeThreshold && abs(dx) > abs(dy) {
                    step(1)
                } else if dx < -swipeThreshold && abs(dx) > abs(dy) {
                    step(-1)
                } else if dy < -swipeThreshold && abs(dy) > abs(dx) {
                    Task { await annotate("keep"); step(1) }
                } else if dy > swipeThreshold && abs(dy) > abs(dx) {
                    Task { await annotate("cull"); step(1) }
                }
                withAnimation(.spring()) { dragOffset = .zero }
            }
    }

    private func step(_ delta: Int) {
        let next = max(0, min(rows.count - 1, index + delta))
        if next != index { index = next }
    }

    private func annotate(_ decision: String) async {
        guard index >= 0 && index < rows.count else { return }
        let row = rows[index]
        savingDecision = decision
        lastError = nil
        do {
            _ = try await api.annotate(runID: runID,
                                        filename: row.filename,
                                        decision: decision)
            // Mutate locally so the grid reflects the new decision
            // on dismiss + the pill updates immediately.
            let updated = RowEntry(
                filename: row.filename,
                decision: decision,
                score_final: row.score_final,
                scene: row.scene,
                cluster_id: row.cluster_id,
                is_burst_peak: row.is_burst_peak,
                rubric_human_labeled: true,
            )
            rows[index] = updated
        } catch {
            lastError = (error as? APIError)?.localizedDescription
                ?? error.localizedDescription
        }
        savingDecision = nil
    }
}
