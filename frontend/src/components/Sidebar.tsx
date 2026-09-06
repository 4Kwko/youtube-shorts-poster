import type { LucideIcon } from "lucide-react";
import { Clapperboard, FolderOpen, House, Settings } from "lucide-react";

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
      <div className="sidebar__brand">
        <span className="sidebar__mark" aria-hidden="true">
          <Clapperboard size={16} />
        </span>
        <span className="sidebar__name">Clipper</span>
      </div>

      <div className="sidebar__nav">
        {NAV_ITEMS.map((key) => {
          const Icon = ICONS[key];
          return (
            <button
              key={key}
              type="button"
              className="sidebar__item"
              aria-current={key === active ? "page" : undefined}
              onClick={() => onNavigate(key)}
            >
              <Icon size={16} />
              {NAV_LABELS[key]}
            </button>
          );
        })}
      </div>

      <div className="sidebar__footer">Clipper {version}</div>
    </nav>
  );
}
