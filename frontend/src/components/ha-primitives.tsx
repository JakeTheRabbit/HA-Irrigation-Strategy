import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import "./ha-primitives.css";

export type HaTone = "primary" | "success" | "warning" | "error" | "neutral";

/** Responsive grid of Home Assistant Mushroom-style KPI tiles at the top of a workspace. */
export function KpiGrid({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`ha-kpi-grid ${className}`.trim()}>{children}</div>;
}

/** One Home Assistant metric tile: soft tinted circular icon badge, bold tabular-nums reading,
 * concise label, and optional sub-label or click target. */
export function KpiCard({
  icon: Icon,
  tone = "primary",
  label,
  value,
  detail,
  onClick,
}: {
  icon: LucideIcon;
  tone?: HaTone;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <span className="ha-kpi-icon" data-tone={tone} aria-hidden="true">
        <Icon size={18} />
      </span>
      <span className="ha-kpi-body">
        <span className="ha-kpi-label">{label}</span>
        <strong className="ha-kpi-value">{value}</strong>
        {detail && <span className="ha-kpi-detail">{detail}</span>}
      </span>
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="ha-kpi-card ha-kpi-interactive" data-tone={tone} onClick={onClick}>
        {inner}
      </button>
    );
  }
  return (
    <div className="ha-kpi-card" data-tone={tone}>
      {inner}
    </div>
  );
}

/** Standard rounded Home Assistant card with optional header bar. */
export function HaCard({
  title,
  subtitle,
  action,
  className = "",
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`ha-card ${className}`.trim()}>
      {(title || action) && (
        <header className="ha-card-head">
          <div className="ha-card-titles">
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action && <div className="ha-card-action">{action}</div>}
        </header>
      )}
      <div className="ha-card-body">{children}</div>
    </section>
  );
}
