// AUTO-GENERATED — DO NOT EDIT BY HAND.
//
// Source of truth: design-system/tokens.json
// Regenerate via:  python scripts/build_design_tokens.py
//
// Companion to BrandKit.swift — that file has the high-level
// SwiftUI primitives (RadialProgress, AISparkline); this one
// has the raw token values straight from the design-system
// JSON, useful when a SwiftUI view needs e.g. exactly --color-
// surface-bg-card without going through a primitive.

import SwiftUI

public enum BrandTokens {

  // MARK: color
  public static let color_accent_default: String = "#c4b9a9"
  public static let color_accent_focus_ring: String = "rgba(216,206,191,0.55)"
  public static let color_accent_glow: String = "rgba(196,185,169,0.40)"
  public static let color_accent_hi: String = "#d8cebf"
  public static let color_accent_soft: String = "rgba(196,185,169,0.14)"
  public static let color_border_default: String = "#2b241a"
  public static let color_border_hi: String = "#3a3122"
  public static let color_brand_gradient: String = "linear-gradient(135deg, #c4b9a9 0%, #988b78 55%, #6a6052 100%)"
  public static let color_brand_gradient_b: String = "linear-gradient(135deg, #5841C7 0%, #9F3FD9 55%, #EE3F8A 100%)"
  public static let color_brand_indigo: String = "#c4b9a9"
  public static let color_brand_indigo_b: String = "#5841C7"
  public static let color_brand_pink: String = "#6a6052"
  public static let color_brand_pink_b: String = "#EE3F8A"
  public static let color_brand_violet: String = "#988b78"
  public static let color_brand_violet_b: String = "#9F3FD9"
  public static let color_decision_cull: String = "#cf6f5b"
  public static let color_decision_cull_cb: String = "#d946ef"
  public static let color_decision_keep: String = "#6faa78"
  public static let color_decision_keep_cb: String = "#0ea5e9"
  public static let color_decision_maybe: String = "#d6a443"
  public static let color_decision_maybe_cb: String = "#f59e0b"
  public static let color_fg_muted: String = "#a89d88"
  public static let color_fg_muted_soft: String = "#7d7361"
  public static let color_fg_primary: String = "#f3ede1"
  public static let color_fg_secondary: String = "#d3c9b6"
  public static let color_semantic_danger: String = "#cf6f5b"
  public static let color_semantic_danger_border: String = "rgba(207,111,91,0.42)"
  public static let color_semantic_danger_tint: String = "rgba(207,111,91,0.15)"
  public static let color_semantic_info: String = "#6ea2b0"
  public static let color_semantic_info_border: String = "rgba(110,162,176,0.42)"
  public static let color_semantic_info_tint: String = "rgba(110,162,176,0.15)"
  public static let color_semantic_neutral: String = "#a89d88"
  public static let color_semantic_neutral_border: String = "rgba(168,157,136,0.30)"
  public static let color_semantic_neutral_tint: String = "rgba(168,157,136,0.10)"
  public static let color_semantic_success: String = "#6faa78"
  public static let color_semantic_success_border: String = "rgba(111,170,120,0.42)"
  public static let color_semantic_success_tint: String = "rgba(111,170,120,0.15)"
  public static let color_semantic_warn: String = "#d6a443"
  public static let color_semantic_warn_border: String = "rgba(214,164,67,0.42)"
  public static let color_semantic_warn_tint: String = "rgba(214,164,67,0.15)"
  public static let color_surface_bg: String = "#161310"
  public static let color_surface_bg_card: String = "#1e1a14"
  public static let color_surface_bg_card_hi: String = "#272118"
  public static let color_surface_chrome: String = "#100d0a"
  public static let color_surface_surface_2: String = "#272118"
  public static let color_surface_surface_3: String = "#322a1e"

  // MARK: font
  public static let font_family_body: String = "Geist Variable, -apple-system, BlinkMacSystemFont, Segoe UI Variable, Segoe UI, PingFang SC, Microsoft Yahei UI, sans-serif"
  public static let font_family_display: String = "Geist Variable, -apple-system, BlinkMacSystemFont, Segoe UI Variable, Segoe UI, PingFang SC, Microsoft Yahei UI, sans-serif"
  public static let font_family_mono: String = "ui-monospace, SF Mono, JetBrains Mono, Menlo, monospace"
  public static let font_family_serif: String = "Charter, Iowan Old Style, PT Serif, Source Serif Pro, Source Serif 4, Cambria, Georgia, Songti SC, STZhongsong, serif"
  public static let font_lineHeight_loose: String = "1.7"
  public static let font_lineHeight_normal: String = "1.55"
  public static let font_lineHeight_tight: String = "1.25"
  public static let font_size_2xl: Double = 18.0
  public static let font_size_3xl: Double = 22.0
  public static let font_size_4xl: Double = 28.0
  public static let font_size_5xl: Double = 36.0
  public static let font_size_6xl: Double = 48.0
  public static let font_size_base: Double = 12.5
  public static let font_size_body: Double = 13.0
  public static let font_size_h2: Double = 18.0
  public static let font_size_h3: Double = 14.0
  public static let font_size_hero: Double = 28.0
  public static let font_size_lg: Double = 14.0
  public static let font_size_md: Double = 13.0
  public static let font_size_sm: Double = 11.5
  public static let font_size_small: Double = 11.5
  public static let font_size_tiny: Double = 10.5
  public static let font_size_xl: Double = 16.0
  public static let font_size_xs: Double = 10.5

  // MARK: motion
  public static let motion_duration_fast: String = "120ms"
  public static let motion_duration_normal: String = "220ms"
  public static let motion_duration_slow: String = "320ms"
  public static let motion_ease_in_out: String = "cubic-bezier(0.4, 0, 0.2, 1)"
  public static let motion_ease_out: String = "cubic-bezier(0.34, 1.56, 0.64, 1)"
  public static let motion_ease_out_flat: String = "cubic-bezier(0.16, 1, 0.3, 1)"
  public static let motion_ease_pixcull_overshoot: String = "cubic-bezier(0.34, 1.56, 0.64, 1)"
  public static let motion_ease_spring: String = "cubic-bezier(0.34, 1.56, 0.64, 1)"

  // MARK: radius
  public static let radius_lg: Double = 13.0
  public static let radius_md: Double = 9.0
  public static let radius_pill: Double = 999.0
  public static let radius_sm: Double = 6.0
  public static let radius_xl: Double = 18.0

  // MARK: shadow
  public static let shadow_lg: String = "0 18px 48px rgba(20,12,4,0.46)"
  public static let shadow_md: String = "0 6px 22px rgba(20,12,4,0.36)"
  public static let shadow_sm: String = "0 1px 3px rgba(20,12,4,0.34)"
  public static let shadow_xl: String = "0 32px 72px rgba(20,12,4,0.52)"

  // MARK: spacing
  public static let spacing_1: Double = 4.0
  public static let spacing_2: Double = 8.0
  public static let spacing_3: Double = 12.0
  public static let spacing_4: Double = 16.0
  public static let spacing_5: Double = 20.0
  public static let spacing_6: Double = 24.0
  public static let spacing_7: Double = 32.0
  public static let spacing_8: Double = 48.0

}
