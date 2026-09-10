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
  public static let color_accent_default: String = "#d5b584"
  public static let color_accent_focus_ring: String = "rgba(234,202,152,0.55)"
  public static let color_accent_glow: String = "rgba(213,181,132,0.40)"
  public static let color_accent_hi: String = "#eaca98"
  public static let color_accent_soft: String = "rgba(213,181,132,0.16)"
  public static let color_border_default: String = "#262626"
  public static let color_border_hi: String = "#363636"
  public static let color_brand_champagne: String = "#d5b584"
  public static let color_brand_champagne_deep: String = "#93743f"
  public static let color_brand_champagne_hi: String = "#eaca98"
  public static let color_brand_champagne_mid: String = "#b5945f"
  public static let color_brand_gradient: String = "linear-gradient(135deg, #d5b584 0%, #93743f 100%)"
  public static let color_brand_wordmark_end: String = "#c2a878"
  public static let color_brand_wordmark_gradient: String = "linear-gradient(135deg, #f2ead9 0%, #dfcfae 55%, #c2a878 100%)"
  public static let color_brand_wordmark_mid: String = "#dfcfae"
  public static let color_brand_wordmark_start: String = "#f2ead9"
  public static let color_decision_cull: String = "#e0604e"
  public static let color_decision_cull_cb: String = "#d946ef"
  public static let color_decision_keep: String = "#63bd7f"
  public static let color_decision_keep_cb: String = "#0ea5e9"
  public static let color_decision_maybe: String = "#d6a443"
  public static let color_decision_maybe_cb: String = "#f59e0b"
  public static let color_fg_muted: String = "#9b9b9b"
  public static let color_fg_muted_soft: String = "#707070"
  public static let color_fg_primary: String = "#e6e6e6"
  public static let color_fg_secondary: String = "#c6c6c6"
  public static let color_semantic_danger: String = "#e0604e"
  public static let color_semantic_danger_border: String = "rgba(207,111,91,0.42)"
  public static let color_semantic_danger_tint: String = "rgba(207,111,91,0.15)"
  public static let color_semantic_info: String = "#72a4b2"
  public static let color_semantic_info_border: String = "rgba(110,162,176,0.42)"
  public static let color_semantic_info_tint: String = "rgba(110,162,176,0.15)"
  public static let color_semantic_neutral: String = "#9b9b9b"
  public static let color_semantic_neutral_border: String = "rgba(168,157,136,0.30)"
  public static let color_semantic_neutral_tint: String = "rgba(168,157,136,0.10)"
  public static let color_semantic_success: String = "#63bd7f"
  public static let color_semantic_success_border: String = "rgba(111,170,120,0.42)"
  public static let color_semantic_success_tint: String = "rgba(111,170,120,0.15)"
  public static let color_semantic_warn: String = "#d6a443"
  public static let color_semantic_warn_border: String = "rgba(214,164,67,0.42)"
  public static let color_semantic_warn_tint: String = "rgba(214,164,67,0.15)"
  public static let color_surface_bg: String = "#161616"
  public static let color_surface_bg_card: String = "#1d1d1d"
  public static let color_surface_bg_card_hi: String = "#242424"
  public static let color_surface_chrome: String = "#0f0f0f"
  public static let color_surface_surface_2: String = "#242424"
  public static let color_surface_surface_3: String = "#2e2e2e"

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

  // Theme: light. Overrides only; anything absent
  // here is shared with the default theme above.
  public enum Light {
    public static let color_accent_default: String = "#6c501f"
    public static let color_accent_hi: String = "#866939"
    public static let color_border_default: String = "#e2e2e2"
    public static let color_border_hi: String = "#c9c9c9"
    public static let color_brand_champagne: String = "#6c501f"
    public static let color_brand_champagne_deep: String = "#2b1c00"
    public static let color_brand_champagne_hi: String = "#866939"
    public static let color_brand_champagne_mid: String = "#4d3401"
    public static let color_decision_cull_cb: String = "#d946ef"
    public static let color_decision_keep_cb: String = "#0ea5e9"
    public static let color_decision_maybe_cb: String = "#f59e0b"
    public static let color_fg_muted: String = "#616165"
    public static let color_fg_muted_soft: String = "#858589"
    public static let color_fg_primary: String = "#171717"
    public static let color_fg_secondary: String = "#3a3a3c"
    public static let color_semantic_danger: String = "#dc2626"
    public static let color_semantic_info: String = "#0e7490"
    public static let color_semantic_neutral: String = "#4b5563"
    public static let color_semantic_success: String = "#059669"
    public static let color_semantic_warn: String = "#c2410c"
    public static let color_surface_bg: String = "#f7f7f7"
    public static let color_surface_bg_card: String = "#fdfdfd"
    public static let color_surface_bg_card_hi: String = "#ececec"
    public static let color_surface_chrome: String = "#fdfdfd"
    public static let color_surface_surface_2: String = "#e9e9e9"
    public static let color_surface_surface_3: String = "#dddddd"
  }

}
