# Design System Specification: Light Mode Transition

## 1. Overview & Creative North Star: "The Ethereal Monolith"
The transition of our "Digital Obsidian" identity into a light-performance environment is not merely an inversion of values-it is a translation of power. We are moving from the depths of a dark terminal into the high-clarity atmosphere of a premium gallery.

**Creative North Star: The Ethereal Monolith.**
This design system rejects the "card-on-grey-background" cliché of SaaS platforms. Instead, it treats the interface as a singular, high-precision instrument carved from porcelain and silver. We achieve authority not through heavy lines, but through intentional asymmetry, massive typographic scales, and "Tonal Sculpting." The layout should feel like an architectural blueprint: airy, high-contrast, and impeccably organized, where the "weight" of an element is determined by its tonal depth rather than its border thickness.

---

## 2. Colors: Tonal Sculpting & The Porcelain Surface
We utilize a palette of high-performance neutrals. The primary surface is not a stark, sterile white, but a sophisticated **Porcelain White (#F5F5F5)** that reduces eye strain while maintaining a "museum-grade" backdrop.

### Surface Hierarchy & Nesting
To move beyond a "template" look, we prohibit the use of 1px solid borders for sectioning. This is the **"No-Line" Rule.** Boundaries are defined strictly through background shifts:
*   **The Foundation:** Use `surface` (#F9F9F9) for the primary application background.
*   **The Inset:** Use `surface_container_low` (#F2F4F4) for sidebars or secondary navigation.
*   **The Elevation:** Use `surface_container_lowest` (#FFFFFF) for the most critical interactive components (like a central workspace), creating a "lit from within" effect.
*   **The Accent:** Use `surface_dim` (#D4DBDD) sparingly for footer areas or inactive states to ground the layout.

### The Glass & Gradient Rule
To inject "soul" into the professional environment:
*   **Glassmorphism:** For floating modals or dropdowns, use `surface_container_lowest` at 80% opacity with a `24px` backdrop blur. This allows the subtle Porcelain and Charcoal tones to bleed through, softening the interface.
*   **Signature Textures:** Main CTAs should utilize a subtle linear gradient from `primary` (#5F5E5E) to `primary_dim` (#535252). This adds a metallic, machined quality that flat HEX codes cannot replicate.

---

## 3. Typography: Editorial Authority
Our typography is the primary driver of the brand's premium feel. We pair the technical precision of **Inter** with the architectural character of **Manrope**.

*   **Display (Manrope):** Use `display-lg` (3.5rem) with tight letter-spacing (-0.02em) for hero moments. This creates a bold, editorial "magazine" feel.
*   **Headlines (Manrope):** `headline-lg` through `sm` serve as the structural anchors. They should be set in `on_surface` (#2D3435) with generous top-margin to allow the content to "breathe."
*   **Body (Inter):** `body-lg` (1rem) is our workhorse. We prioritize legibility by using `on_surface_variant` (#5A6061) for secondary descriptions, creating a sophisticated gray-scale hierarchy.
*   **Labels (Inter):** `label-md` and `sm` are reserved for metadata and micro-copy, always set in `on_secondary_fixed_variant` (#5A5C5C) for a muted, technical look.

---

## 4. Elevation & Depth: Tonal Layering
In this design system, shadows are a last resort. Depth is an architectural exercise in stacking.

*   **The Layering Principle:** A "card" is not a box with a shadow. A card is a `surface_container_lowest` (#FFFFFF) shape sitting on a `surface_container` (#EBEEEF) background.
*   **Ambient Shadows:** If an element must float (e.g., a Global Search bar), use an "Atmospheric Shadow": `0px 20px 40px rgba(45, 52, 53, 0.06)`. This mimics natural light diffusion rather than a digital drop shadow.
*   **The Ghost Border:** For high-density data where separation is vital, use a "Ghost Border": `1px solid` using the `outline_variant` token (#ADB3B4) at **15% opacity**. It should be felt, not seen.
*   **Intentional Asymmetry:** Break the grid. Allow certain images or data visualizations to bleed off the edge of their containers, or overlap two surface layers to create visual tension and interest.

---

## 5. Components: Precision Primitives

### Buttons: The Metallic Touch
*   **Primary:** A gradient of `primary` to `primary_dim` with `on_primary` (#FAF7F6) text. Border-radius: `md` (0.375rem).
*   **Secondary:** `surface_container_highest` background with `on_surface` text. No border.
*   **Tertiary:** Transparent background with `primary` text. Upon hover, shift to `surface_container_low`.

### Input Fields: Institutional Precision
*   **Structure:** No background. Only a bottom-border of 1px using `outline_variant` at 40% opacity.
*   **Focus:** The bottom-border transitions to `primary` (#5F5E5E) with a height of 2px. The label (`label-md`) shifts to `primary` color.

### Cards & Lists: The Separation Rule
*   **Forbid Divider Lines:** Use `16px` or `24px` of vertical white space to separate list items.
*   **Alternate Row Shading:** For high-density tables, use a subtle shift between `surface` and `surface_container_low` instead of horizontal lines.

### Chips: The Silver Accent
*   **Filter Chips:** Use `secondary_container` (#E3E2E2) with `on_secondary_container` (#515252) text. Use the `full` (9999px) roundedness scale to create a pill shape that contrasts with the architectural squareness of the rest of the UI.

---

## 6. Do's and Don'ts

### Do:
*   **Do** use extreme white space. If you think there is enough padding, add 8px more.
*   **Do** use `surface_bright` to highlight the most "active" part of a multi-panel layout.
*   **Do** ensure all typography maintains a minimum contrast ratio of 4.5:1 against the porcelain surfaces.

### Don't:
*   **Don't** use 100% black (#000000). Use `on_surface` (#2D3435) to keep the "Charcoal" aesthetic sophisticated.
*   **Don't** use standard 1px borders to create a grid. The grid should be felt through the alignment of text and the shift in background tones.
*   **Don't** use vibrant colors for accents. Our "Metallic Silver" and "Charcoal" define the palette. Status colors (Error/Success) must be muted and integrated into the tonal scale.