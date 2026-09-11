"use client";

/**
 * Read-only advisory banner used across analytical surfaces (Risk, Alpha,
 * Matrix). Nexus is intentionally non-execution; every numeric output is a
 * statistical estimate. The banner is the canonical disclosure surface so
 * this caveat is visible without nagging on every panel.
 */

interface Props {
  /** Override the body copy when context is more specific than the default. */
  message?: string;
  /** Override the eyebrow tag. Default "ADVISORY". */
  tag?: string;
}

const DEFAULT_BODY =
  "Read-only intelligence. Position-sizing, VaR and circuit-breaker outputs " +
  "are statistical estimates - not investment advice or order instructions.";

export default function AdvisoryNotice({ message, tag = "ADVISORY" }: Props) {
  return (
    <div
      role="note"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 12px",
        background: "rgba(198,198,199,0.04)",
        border: "1px solid var(--hairline)",
        borderLeft: "2px solid var(--primary)",
        borderRadius: 3,
        fontSize: 10,
        letterSpacing: "0.10em",
        color: "var(--on-surface-variant)",
        flex: "0 0 auto",
      }}
    >
      <span style={{ color: "var(--primary)", fontWeight: 700, letterSpacing: "0.18em", flex: "0 0 auto" }}>
        {tag}
      </span>
      <span style={{ color: "var(--on-surface)" }}>{message ?? DEFAULT_BODY}</span>
    </div>
  );
}
