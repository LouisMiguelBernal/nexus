# Design System: Institutional Intelligence

## 1. Overview & Creative North Star
**Creative North Star: "The Digital Obsidian"**

This design system is engineered for high-stakes financial environments where data density meets executive precision. Unlike consumer-grade dashboards that rely on "friendly" rounded corners and vibrant colors, this system is an exercise in restraint and surgical clarity. It represents a fusion of the raw informational power of a Bloomberg Terminal with the refined, tactile hardware aesthetic of Apple’s Pro line.

The interface is not a flat canvas; it is a deep, multi-layered environment. We break the "template" look through intentional asymmetry-using dense data clusters (radar charts, sparklines) balanced against expansive, "breathing" porcelain typography. We favor tonal depth over structural lines, ensuring the UI feels like a single, cohesive instrument rather than a collection of boxes.

---

## 2. Colors & Atmospheric Depth
The palette is rooted in a monochromatic spectrum that prioritizes focus and minimizes cognitive load.

### Surface Hierarchy & Nesting
Instead of a flat grid, we use "Nesting" to define hierarchy. 
- **The "No-Line" Rule:** Sectioning must be achieved through background shifts, not 1px solid lines. A `surface_container_lowest` card sits on a `surface_container_low` section, creating a natural edge.
- **Glassmorphism:** For floating modals or dropdowns (e.g., the User Profile menu), use semi-transparent `surface_container_high` with a 20px backdrop-blur to create a "frosted obsidian" look.
- **Signature Glows:** Use `primary` (#c6c6c7) as a 1px "Silver Glow" on the top edge of critical containers to simulate light hitting a chamfered metal edge.

| Role | Token | Value | Intent |
| :--- | :--- | :--- | :--- |
| **Base Background** | `surface` | #0e0e0e | The deep charcoal foundation. |
| **Primary Text** | `on_surface` | #e7e5e4 | Porcelain white for maximum legibility. |
| **Secondary Text** | `on_surface_variant` | #acabaa | De-emphasized metadata and labels. |
| **Accent / Metal** | `primary` | #c6c6c7 | Metallic silver for interactive states. |
| **Critical/Alert** | `error` | #ee7d77 | High-performance alert (market drops). |

---

## 3. Typography
We utilize **Inter** (or SF Pro) exclusively. The weight is kept at **Medium (500)** for most data to ensure clarity against the dark background, avoiding the "bleeding" effect thin fonts often have on OLED displays.

- **Display Scale:** Use `display-lg` (3.5rem) sparingly for portfolio totals. It should feel editorial-massive, yet quiet.
- **Data Density:** `label-sm` (0.6875rem) is our workhorse for sparkline labels and ticker codes.
- **Authoritative Titles:** `title-lg` (1.375rem) uses increased letter-spacing (-0.02em) to mimic high-end financial reporting.

---

## 4. Elevation & Depth
Depth is a functional tool, not a stylistic flourish.

- **Tonal Layering:** The primary method of elevation. 
    - Level 0: `surface` (Main canvas)
    - Level 1: `surface_container_low` (Sidebar/Background sections)
    - Level 2: `surface_container_highest` (Active cards/Trading modules)
- **Ambient Shadows:** For "floating" elements like the "Partial Exit" menu, use a shadow with a 40px blur at 8% opacity using the `on_surface` color. It should feel like a soft light source is behind the glass, not a "drop shadow."
- **The "Ghost Border" Fallback:** If a separator is required for high-density data tables, use `outline_variant` at 15% opacity. Never use 100% opaque lines.

---

## 5. Components

### Buttons & Interaction
- **Primary:** Metallic gradient from `primary` to `primary_dim`. High-contrast text (`on_primary`). No rounded corners-use `sm` (0.125rem) for a sharp, "machined" look.
- **Tertiary:** Purely typographic with a subtle `primary` underline on hover.

### Data Visualization (The "NEXUS" Special)
- **Sparklines:** Use `primary` for neutral trends and `error` for downward trends. Lines should be 1.5px thick with a subtle glow (0 0 8px) of the same color.
- **Radar Charts:** Use `surface_variant` for the grid and a semi-transparent `primary` fill for the data area.

### Input Fields & Controls
- **Inputs:** `surface_container_lowest` background with an `outline_variant` "Ghost Border." On focus, the border transitions to a `primary` (Silver) 1px glow.
- **Cards & Lists:** **Prohibit divider lines.** Use vertical white space (16px/24px) or a background shift to `surface_container_high` to separate MSFT from AAPL in a watchlist.

### Navigation
- **Active State:** A vertical 2px silver bar (`primary`) to the left of the menu item, paired with a subtle shift to `on_surface` from `on_surface_variant`.

---

## 6. Do's and Don'ts

### Do
- **DO** use asymmetry. Place a heavy radar chart on the right against a clean, porcelain headline on the left.
- **DO** lean into "Precision Micro-copy." Instead of "Change," use "Delta (%)" or "Basis Points."
- **DO** use the `sm` (2px) radius. Sharp corners convey "Institutional/Professional."

### Don't
- **DON'T** use pure white (#FFFFFF). It causes eye strain. Always use the Porcelain `on_surface` (#e7e5e4).
- **DON'T** use standard Material Design "Floating Action Buttons." They are too playful for this context. Use integrated top-bar actions.
- **DON'T** use 1px solid borders to create "boxes." Let the background colors do the heavy lifting.