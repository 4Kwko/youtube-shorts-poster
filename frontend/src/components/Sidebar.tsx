import type { LucideIcon } from "lucide-react";
import { FolderOpen, House, Settings, Video } from "lucide-react";
import { Logo } from "./Logo";
import type { NavKey } from "../lib/navigation";
import { NAV_ITEMS, NAV_LABELS } from "../lib/navigation";
interface Props {
  active: NavKey;
  onNavigate: (key: NavKey) => void;
  version: string;
}
const ICONS: Record<NavKey, LucideIcon> = {
  home: House,
  projects: FolderOpen,
  settings: Settings,
};
export function Sidebar({ active, onNavigate, version }: Props) {
  return (
    <nav className="sidebar" aria-label="Navegação principal">
      <button
        type="button"
        className="sidebar__brand"
        onClick={() => onNavigate("home")}
        aria-label="SignalCut — Home"
      >
        <Logo />
      </button>
      <span className="sidebar__section">WORKSPACE</span>
      <div className="sidebar__nav">
        {NAV_ITEMS.map((key) => {
          const Icon = ICONS[key];
          return (
            <button
              key={key}
              type="button"
              className="sidebar__item"
              aria-label={NAV_LABELS[key]}
              title={NAV_LABELS[key]}
              aria-current={key === active ? "page" : undefined}
              onClick={() => onNavigate(key)}
            >
              <Icon size={18} strokeWidth={1.7} aria-hidden="true" />
              <span>{NAV_LABELS[key]}</span>
            </button>
          );
        })}
      </div>
      <div className="sidebar__bottom">
        <div className="sidebar__note">
          <Video size={18} aria-hidden="true" />
          <span>
            Do vídeo ao Short.<small>Um corte de cada vez.</small>
          </span>
        </div>
        <div className="sidebar__footer">
          <span>SignalCut</span>
          <span className="mono">v{version}</span>
        </div>
      </div>
    </nav>
  );
}
