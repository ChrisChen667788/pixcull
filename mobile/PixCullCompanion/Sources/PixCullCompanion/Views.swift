// P2.1 — SwiftUI views: settings, run list, run detail, embedded browser.
//
// V0.1 scope is intentionally narrow: read-only review of runs the
// Mac/NAS has already analyzed. The native grid + per-photo
// annotation flows are V0.2.

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
                        Button("Open full results page") {
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
