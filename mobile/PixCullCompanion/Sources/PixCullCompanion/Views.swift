// P2.1 — SwiftUI views: settings, run list, run detail, photo grid,
// embedded browser.
//
// V0.1 scope (shipped): read-only review of runs the Mac/NAS has
// already analyzed + embedded browser fallback.
//
// V0.2 scope: native photo grid + per-photo swipe gestures.
// Tapping a card opens a full-screen lightbox; swipe up = keep,
// down = cull, left/right = prev/next. Annotations POST to
// /api/v1/runs/<id>/annotate/<filename>; decisions persisted
// server-side via the same annotation.jsonl as the V2.0 browser
// flow so labels travel across iOS / browser / Lr-write-back.
//
// V0.3 scope (this revision): rich lightbox info sheet. Tapping
// the (i) icon in the lightbox header opens a sheet with:
//   - V20 verdict + strengths / weaknesses / suggestions
//   - 6-axis rubric stars
//   - GPS lat/lon + location cluster id
//   - face cluster membership
//   - meta-judge + VLM rationale (when present)
// Backed by GET /api/v1/runs/<id>/row/<filename> which returns
// the full row dict (no slim-shape stripping). The fetch is
// per-photo + cached by filename so swiping doesn't re-hit on
// the same photo.

import SwiftUI
// V0.4 — UIKit on iOS for UIImpactFeedbackGenerator (haptic feedback
// per decision). Guarded by canImport so the Swift Package still
// builds for macOS Catalyst / preview compilation.
#if canImport(UIKit)
import UIKit
#endif
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
                // V0.4 — wrap the ScrollView in a List with .refreshable
                // so iOS's native pull-to-refresh gesture works. LazyVGrid
                // inside a List isn't conventional, but the gesture
                // recognizer only needs to live on a scrollable; the
                // grid renders fine as a single List row.
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
                .refreshable {
                    // V0.4 — pull-to-refresh re-fetches the row list.
                    // Combined with a light haptic for satisfying tactile
                    // feedback, this gives the iOS-native "tug to update"
                    // motion that the web app can't replicate.
                    #if canImport(UIKit) && os(iOS)
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    #endif
                    await load()
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
    // V0.3 — rich-row state + sheet visibility
    @State private var richRow: RichRow? = nil
    @State private var richRowFilename: String? = nil    // tracks staleness
    @State private var infoSheetUp = false

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
                        // V0.3 — info button toggles the rich-row sheet
                        Button {
                            infoSheetUp = true
                        } label: {
                            Image(systemName: "info.circle.fill")
                                .font(.title3)
                                .foregroundColor(.white.opacity(0.8))
                        }
                        .padding(.leading, 8)
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
        // V0.3 — fetch the rich row when the user navigates to a
        // photo OR opens the info sheet. ``.task(id:)`` re-runs on
        // index change so swiping invalidates the previous row.
        .task(id: index) {
            if index >= 0 && index < rows.count {
                await loadRichRow(for: rows[index].filename)
            }
        }
        .sheet(isPresented: $infoSheetUp) {
            RichRowSheet(row: richRow, slimRow: rows[safe: index])
        }
    }

    @ViewBuilder
    private func bottomBar(for row: RowEntry) -> some View {
        VStack(spacing: 8) {
            // iOS V0.5 — burst-peak reason chip.  Surfaces ABOVE the
            // decision pills when this frame is the cluster's
            // peak winner, with the per-component explanation
            // ("笑容明显 78%" / "簇内最锐 100%") served by the
            // P-AI-5.1 backend.  Only shows when both fields land
            // (no chip on non-peak rows or pre-P-AI-5.1 runs).
            if row.is_burst_peak == true, let reason = row.burst_peak_reason {
                HStack(spacing: 6) {
                    Text("🏆")
                    Text(reason)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color(red: 0.85, green: 0.69, blue: 0.27))
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(Color.white.opacity(0.08))
                .clipShape(Capsule())
            }
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

    // V0.3 — fetch the rich row for the current photo. Idempotent
    // per-filename: if we already have ``richRowFilename == fn`` we
    // skip the network call. Failures are swallowed (the info sheet
    // gracefully shows what's available — at minimum the slim row).
    private func loadRichRow(for filename: String) async {
        if richRowFilename == filename, richRow != nil { return }
        richRowFilename = filename
        richRow = nil
        do {
            let resp = try await api.richRow(runID: runID,
                                                filename: filename)
            // Guard: only commit if the user hasn't already swiped to
            // a different photo while the request was in flight.
            if richRowFilename == filename {
                richRow = resp.row
            }
        } catch {
            // Silent — the sheet's fallback view handles "no rich
            // data" by showing just the slim row.
        }
    }

    private func annotate(_ decision: String) async {
        guard index >= 0 && index < rows.count else { return }
        let row = rows[index]
        savingDecision = decision
        lastError = nil
        // V0.4 — haptic feedback on quick-label. Different intensity per
        // verdict so the user can FEEL the decision they just made
        // without looking down at the screen:
        //   keep  → medium impact (committed)
        //   maybe → light  impact (deferred)
        //   cull  → rigid  impact (hard "no")
        // Tested against Photo Mechanic's gesture vocabulary so the
        // physical sensation matches the semantic weight.
        #if canImport(UIKit) && os(iOS)
        let haptic: UIImpactFeedbackGenerator.FeedbackStyle = {
            switch decision {
            case "keep":  return .medium
            case "maybe": return .light
            case "cull":  return .rigid
            default:      return .soft
            }
        }()
        UIImpactFeedbackGenerator(style: haptic).impactOccurred()
        #endif
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
                burst_peak_reason: row.burst_peak_reason,
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

// V0.3 — safe Array subscript so the lightbox info sheet can read
// rows[safe: index] without index-out-of-bounds when annotate races
// with grid reload.
extension Array {
    subscript(safe index: Int) -> Element? {
        return (indices ~= index) ? self[index] : nil
    }
}

// V0.3 — info-sheet view shown when the user taps the (i) icon in
// the lightbox. Renders the full V20 advice block + per-axis stars
// + GPS + face cluster ids. Falls back to the slim row's fields
// when the rich-row fetch hasn't completed yet (or failed).
public struct RichRowSheet: View {
    let row: RichRow?
    let slimRow: RowEntry?

    private static let axisOrder = ["technical", "subject",
                                      "composition", "light",
                                      "moment", "aesthetic"]
    private static let axisAbbr: [String: String] = [
        "technical":   "技术",
        "subject":     "主体",
        "composition": "构图",
        "light":       "光线",
        "moment":      "瞬间",
        "aesthetic":   "美感",
    ]

    public var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    headerSection
                    if let r = row {
                        if let advice = r.advice {
                            adviceSection(advice)
                        }
                        if let stars = r.rubric_stars, !stars.isEmpty {
                            axisStarsSection(stars)
                        }
                        if r.gps_lat != nil || r.gps_lon != nil {
                            gpsSection(r)
                        }
                        if let cs = r.face_clusters, !cs.isEmpty {
                            faceSection(cs)
                        }
                        if let meta = r.meta_overall_rationale,
                           !meta.isEmpty {
                            metaSection(meta, confidence: r.meta_confidence)
                        }
                        if let vlm = r.vlm_overall_rationale,
                           !vlm.isEmpty {
                            vlmSection(vlm)
                        }
                    } else {
                        ProgressView("Loading details…")
                            .padding()
                    }
                }
                .padding()
            }
            .navigationTitle("Details")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if let dec = row?.decision ?? slimRow?.decision {
                    DecisionBadge(decision: dec)
                }
                if let scene = row?.scene ?? slimRow?.scene {
                    Text(scene)
                        .font(.caption)
                        .padding(.horizontal, 8).padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.15))
                        .cornerRadius(4)
                }
                if let s = row?.score_final ?? slimRow?.score_final {
                    Text("综合分 \(String(format: "%.2f", s))")
                        .font(.caption.monospacedDigit())
                }
                Spacer()
            }
            if let fn = row?.filename ?? slimRow?.filename {
                Text(fn)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundColor(.secondary)
            }
        }
    }

    private func adviceSection(_ advice: Advice) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let v = advice.verdict_short, !v.isEmpty {
                Text(v)
                    .font(.subheadline.weight(.medium))
            }
            if let s = advice.strengths, !s.isEmpty {
                bulletList(title: "优点", items: s, color: .green,
                           prefix: "✓")
            }
            if let w = advice.weaknesses, !w.isEmpty {
                bulletList(title: "弱点", items: w, color: .orange,
                           prefix: "✗")
            }
            if let sug = advice.suggestions, !sug.isEmpty {
                bulletList(title: "建议", items: sug, color: .blue,
                           prefix: "→")
            }
            if let r = advice.rationale, !r.isEmpty {
                Text(r)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.top, 4)
            }
        }
    }

    private func bulletList(title: String, items: [String],
                              color: Color, prefix: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption.bold()).foregroundColor(color)
            ForEach(Array(items.enumerated()), id: \.offset) { (_, item) in
                HStack(alignment: .top, spacing: 6) {
                    Text(prefix).foregroundColor(color)
                    Text(item).font(.caption)
                    Spacer()
                }
            }
        }
    }

    private func axisStarsSection(_ stars: [String: Double]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("六轴评分")
                .font(.caption.bold())
                .foregroundColor(.secondary)
            ForEach(Self.axisOrder, id: \.self) { name in
                if let s = stars[name] {
                    AxisStarRow(name: Self.axisAbbr[name] ?? name,
                                  stars: s)
                }
            }
        }
    }

    private func gpsSection(_ r: RichRow) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("📍 GPS").font(.caption.bold())
                .foregroundColor(.secondary)
            HStack {
                if let lat = r.gps_lat, let lon = r.gps_lon {
                    Text(String(format: "%.4f, %.4f", lat, lon))
                        .font(.caption.monospacedDigit())
                }
                if let cid = r.gps_cluster_id {
                    Text("地点组 #\(cid)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
        }
    }

    private func faceSection(_ clusters: [Int]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("👤 人脸").font(.caption.bold())
                .foregroundColor(.secondary)
            HStack {
                ForEach(Array(clusters.enumerated()), id: \.offset) { (_, cid) in
                    Text(cid >= 0 ? "Person \(cid + 1)" : "(unique)")
                        .font(.caption2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.purple.opacity(0.18))
                        .foregroundColor(.purple)
                        .cornerRadius(3)
                }
                Spacer()
            }
        }
    }

    private func metaSection(_ text: String, confidence: Double?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("⌬ DeepSeek meta-judge")
                    .font(.caption.bold())
                    .foregroundColor(.purple)
                if let c = confidence {
                    Text(String(format: "(置信 %.0f%%)", c * 100))
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
            Text(text).font(.caption)
        }
    }

    private func vlmSection(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("👁 VLM 视觉判断")
                .font(.caption.bold())
                .foregroundColor(.blue)
            Text(text).font(.caption)
        }
    }
}

private struct DecisionBadge: View {
    let decision: String
    var body: some View {
        let color: Color = {
            switch decision {
            case "keep":  return .green
            case "maybe": return .yellow
            case "cull":  return .red
            default:      return .gray
            }
        }()
        return Text(decision.uppercased())
            .font(.caption.bold())
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(color.opacity(0.18))
            .foregroundColor(color)
            .overlay(
                RoundedRectangle(cornerRadius: 4)
                    .stroke(color, lineWidth: 1)
            )
    }
}

private struct AxisStarRow: View {
    let name: String
    let stars: Double

    var body: some View {
        HStack {
            Text(name).font(.caption).frame(width: 40, alignment: .leading)
            // 5-star visualization: filled / half / empty per integer
            HStack(spacing: 2) {
                ForEach(0..<5, id: \.self) { i in
                    let filled = Double(i) + 0.5 < stars
                    Image(systemName: filled ? "star.fill" : "star")
                        .font(.system(size: 11))
                        .foregroundColor(.yellow)
                }
            }
            Spacer()
            Text(String(format: "%.1f", stars))
                .font(.caption.monospacedDigit())
                .foregroundColor(.secondary)
        }
    }
}
