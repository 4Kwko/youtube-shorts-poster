import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "icon";
  loading?: boolean;
}
export function Button({
  variant = "secondary",
  loading = false,
  disabled,
  children,
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`button button--${variant} ${className}`}
    >
      {loading && (
        <LoaderCircle size={16} className="spinner" aria-hidden="true" />
      )}
      {children}
    </button>
  );
}
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
  children: ReactNode;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
export function Progress({ value, label }: { value: number; label: string }) {
  const bounded = Math.max(0, Math.min(100, value));
  return (
    <div
      className="progress__track"
      role="progressbar"
      aria-label={label}
      aria-valuenow={bounded}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="progress__bar" style={{ width: `${bounded}%` }} />
    </div>
  );
}
export function TimelineArt() {
  return (
    <svg
      className="timeline-art"
      viewBox="0 0 240 100"
      fill="none"
      aria-hidden="true"
    >
      <path d="M12 18h216M12 82h216" stroke="currentColor" opacity=".3" />
      {Array.from({ length: 15 }, (_, i) => (
        <path
          key={i}
          d={`M${15 + i * 15} 12v${i % 5 === 0 ? 10 : 5}`}
          stroke="currentColor"
          opacity=".4"
        />
      ))}
      <rect
        x="18"
        y="32"
        width="82"
        height="38"
        rx="6"
        fill="currentColor"
        opacity=".08"
      />
      <rect
        x="109"
        y="32"
        width="113"
        height="38"
        rx="6"
        stroke="currentColor"
        opacity=".3"
      />
      <path
        d="M27 51h12l5-10 6 22 7-29 7 25 7-17 5 9h15M120 51h15l5-10 6 22 7-29 7 25 7-17 5 9h40"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path d="M105 22v66" stroke="var(--accent)" strokeWidth="2" />
      <path d="m100 22 5 6 5-6" fill="var(--accent)" />
    </svg>
  );
}
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <TimelineArt />
      <h2>{title}</h2>
      <p className="empty__hint">{children}</p>
      {action}
    </div>
  );
}
