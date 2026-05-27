// v0.10-P0-4 — single source of brand identity for the iOS Companion.
//
// Mirrors the v0.9-P0-3 brand kit + v0.9-P1-4 AI visualization from
// the web app (see results.html: --brand-gradient, .ai-num,
// .score-radial, .ai-sparkline).  Keeping the palette + helper
// shapes in one Swift file makes it cheap to keep iOS aligned with
// web as the brand evolves.

import SwiftUI

public enum Brand {
    // Same three stops the web's --brand-gradient uses.
    public static let indigo = Color(red: 0x6E/255.0, green: 0x56/255.0, blue: 0xCF/255.0)
    public static let violet = Color(red: 0xA8/255.0, green: 0x55/255.0, blue: 0xF7/255.0)
    public static let pink   = Color(red: 0xEC/255.0, green: 0x48/255.0, blue: 0x99/255.0)

    public static let gradient = LinearGradient(
        gradient: Gradient(colors: [indigo, violet, pink]),
        startPoint: .topLeading,
        endPoint:   .bottomTrailing
    )

    // Verticalised variant for sparkline area fills (top → bottom
    // wash matches the web's #aiBrandGradV).
    public static let gradientVertical = LinearGradient(
        gradient: Gradient(colors: [indigo, pink]),
        startPoint: .top,
        endPoint:   .bottom
    )
}

// MARK: - Brand-gradient text

/// Applies the brand gradient as the text fill, matching the web's
/// `.ai-num` class.  Used on score_final, hero numerals on the
/// portfolio share view, etc.
public extension View {
    @ViewBuilder
    func brandGradient() -> some View {
        self.foregroundStyle(Brand.gradient)
    }
}

// MARK: - Radial progress (mirrors web's .score-radial)

/// 0..1 fill ring around a score number.  Sized via the .frame()
/// modifier the caller wires up — defaults to 18×18 on the small
/// variant and 36×36 on the .lg variant, matching the web.
public struct RadialProgress: View {
    public let score: Double?         // nil → renders empty ring
    public let lineWidth: CGFloat

    public init(score: Double?, lineWidth: CGFloat = 2.5) {
        self.score = score
        self.lineWidth = lineWidth
    }

    public var body: some View {
        ZStack {
            Circle()
                .stroke(Color.white.opacity(0.08), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: CGFloat(max(0, min(1, score ?? 0))))
                .stroke(Brand.gradient,
                        style: StrokeStyle(lineWidth: lineWidth,
                                            lineCap: .round))
                .rotationEffect(.degrees(-90))   // start at 12 o'clock
                .animation(.spring(response: 0.28, dampingFraction: 0.7),
                           value: score)
        }
    }
}

// MARK: - Sparkline (mirrors web's .ai-sparkline)

/// 6-axis (or N-axis) line graph with brand-gradient stroke + 18%
/// area-under-the-curve fill.  Returns a placeholder centerline
/// when fewer than 2 axes have values.
public struct AISparkline: View {
    public let values: [Double?]      // nil entries skipped
    public let aspect: CGFloat        // height / width

    public init(values: [Double?], aspect: CGFloat = 36.0 / 280.0) {
        self.values = values
        self.aspect = aspect
    }

    public var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = w * aspect
            let padX: CGFloat = 6
            let padY: CGFloat = 4
            let nonNil = values.enumerated().compactMap { i, v in
                v.map { (i, $0) }
            }
            ZStack {
                // baseline midline
                Path { p in
                    let midY = h - padY - 0.5 * (h - padY * 2)
                    p.move(to:    CGPoint(x: padX,         y: midY))
                    p.addLine(to: CGPoint(x: w - padX,     y: midY))
                }
                .stroke(Color.white.opacity(0.06), style:
                        StrokeStyle(lineWidth: 1, dash: [2, 3]))

                if nonNil.count >= 2 {
                    sparkArea(width: w, height: h, padX: padX, padY: padY,
                              points: nonNil)
                    sparkLine(width: w, height: h, padX: padX, padY: padY,
                              points: nonNil)
                    sparkDots(width: w, height: h, padX: padX, padY: padY,
                              points: nonNil)
                }
            }
            .frame(width: w, height: h)
        }
        .aspectRatio(1.0 / aspect, contentMode: .fit)
    }

    private func y(for value: Double, in h: CGFloat, padY: CGFloat) -> CGFloat {
        // values in 1..5 → top = 5, bottom = 1
        let clamped = min(5.0, max(1.0, value))
        return h - padY - CGFloat((clamped - 1.0) / 4.0) * (h - padY * 2)
    }

    private func pts(_ pairs: [(Int, Double)], _ w: CGFloat, _ h: CGFloat,
                     _ padX: CGFloat, _ padY: CGFloat) -> [CGPoint] {
        let usable = w - padX * 2
        let stepX = usable / CGFloat(max(1, values.count - 1))
        return pairs.map { i, v in
            CGPoint(x: padX + CGFloat(i) * stepX,
                    y: y(for: v, in: h, padY: padY))
        }
    }

    private func sparkArea(width w: CGFloat, height h: CGFloat,
                            padX: CGFloat, padY: CGFloat,
                            points: [(Int, Double)]) -> some View {
        let pts = pts(points, w, h, padX, padY)
        return Path { p in
            guard let first = pts.first, let last = pts.last else { return }
            p.move(to: first)
            for q in pts.dropFirst() { p.addLine(to: q) }
            p.addLine(to: CGPoint(x: last.x, y: h - padY))
            p.addLine(to: CGPoint(x: first.x, y: h - padY))
            p.closeSubpath()
        }
        .fill(Brand.gradientVertical.opacity(0.18))
    }

    private func sparkLine(width w: CGFloat, height h: CGFloat,
                            padX: CGFloat, padY: CGFloat,
                            points: [(Int, Double)]) -> some View {
        let pts = pts(points, w, h, padX, padY)
        return Path { p in
            guard let first = pts.first else { return }
            p.move(to: first)
            for q in pts.dropFirst() { p.addLine(to: q) }
        }
        .stroke(Brand.gradient,
                style: StrokeStyle(lineWidth: 2, lineCap: .round,
                                    lineJoin: .round))
    }

    private func sparkDots(width w: CGFloat, height h: CGFloat,
                            padX: CGFloat, padY: CGFloat,
                            points: [(Int, Double)]) -> some View {
        let pts = pts(points, w, h, padX, padY)
        return ZStack {
            ForEach(0..<pts.count, id: \.self) { i in
                Circle()
                    .fill(Brand.gradient)
                    .frame(width: 4, height: 4)
                    .position(pts[i])
            }
        }
    }
}
