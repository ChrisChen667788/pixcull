// v0.10-P0-4 — iPad / iPhone gesture set for the photo detail view.
//
// Mirrors the v0.9-P1-5 web behavior:
//   * 1-finger horizontal swipe ≥ 60 px → prev/next photo
//   * 1-finger vertical swipe down ≥ 100 px → dismiss
//   * 1-finger drag while zoomed → pan
//   * 2-finger pinch → zoom around midpoint
//   * tap < 8 px in < 220 ms → toggle fit ↔ 1:1
//
// v0.12-P1-4 — haptic feedback on every coarse-grained interaction:
//   * swipe-nav (prev/next) → light impact
//   * dismiss via swipe-down → medium impact
//   * zoom toggle (fit → 1:1) → soft impact (selection-level)
//   * decision keep/maybe/cull → tier-graded (Views.swift line 793, pre-existing)
//
// Apple HIG: UIImpactFeedbackGenerator on iPad gives the same tactile
// signature on iOS 17+ — keyboard / hover / direct-touch all share
// the same haptic API in this scope.

import SwiftUI
import UIKit   // UIImpactFeedbackGenerator

public struct PhotoGestureModifier: ViewModifier {
    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var tapStart: Date?

    public let onPrev:    () -> Void
    public let onNext:    () -> Void
    public let onDismiss: () -> Void

    private let swipeNav:   CGFloat = 60
    private let swipeClose: CGFloat = 100

    public init(onPrev: @escaping () -> Void,
                 onNext: @escaping () -> Void,
                 onDismiss: @escaping () -> Void) {
        self.onPrev = onPrev
        self.onNext = onNext
        self.onDismiss = onDismiss
    }

    public func body(content: Content) -> some View {
        content
            .scaleEffect(scale)
            .offset(offset)
            .gesture(
                SimultaneousGesture(
                    pinchGesture,
                    dragGesture
                )
            )
            .onTapGesture { toggleZoom() }
            .animation(.spring(response: 0.28, dampingFraction: 0.78),
                       value: scale)
            .animation(.spring(response: 0.28, dampingFraction: 0.78),
                       value: offset)
    }

    private var pinchGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                scale = max(1.0, min(4.0, lastScale * value))
            }
            .onEnded { _ in
                lastScale = scale
                if scale <= 1.001 {
                    offset = .zero
                    lastOffset = .zero
                }
            }
    }

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if scale > 1.001 {
                    // panning a zoomed photo
                    offset = CGSize(
                        width:  lastOffset.width  + value.translation.width,
                        height: lastOffset.height + value.translation.height
                    )
                } else {
                    // partial follow on swipe so the user feels feedback
                    offset = CGSize(
                        width:  value.translation.width  * 0.6,
                        height: max(0, value.translation.height) * 0.6
                    )
                }
            }
            .onEnded { value in
                let dx = value.translation.width
                let dy = value.translation.height
                let absX = abs(dx); let absY = abs(dy)
                if scale > 1.001 {
                    // pan completed
                    lastOffset = offset
                    return
                }
                // fit mode — classify gesture
                if absX > swipeNav && absX > absY {
                    // v0.12-P1-4 — light haptic on swipe-nav
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    if dx < 0 { onNext() } else { onPrev() }
                    offset = .zero
                } else if dy > swipeClose && absY > absX {
                    // v0.12-P1-4 — medium haptic on dismiss (heavier event)
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                    onDismiss()
                    offset = .zero
                } else {
                    // sub-threshold → snap back
                    offset = .zero
                }
            }
    }

    private func toggleZoom() {
        // v0.12-P1-4 — selection-style haptic on zoom-mode change.
        // Selection feedback is the quietest variant — fits the
        // "view-mode switch" semantics better than impact.
        UISelectionFeedbackGenerator().selectionChanged()
        if scale > 1.001 {
            scale = 1.0
            lastScale = 1.0
            offset = .zero
            lastOffset = .zero
        } else {
            scale = 2.0
            lastScale = 2.0
        }
    }
}

public extension View {
    /// Attach the v0.10-P0-4 iPad/iPhone photo-gesture suite.
    func photoGestures(prev: @escaping () -> Void,
                        next: @escaping () -> Void,
                        dismiss: @escaping () -> Void) -> some View {
        modifier(PhotoGestureModifier(onPrev: prev,
                                       onNext: next,
                                       onDismiss: dismiss))
    }
}
