import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { EngineStatusPill } from "./EngineStatusPill";
import { Sidebar } from "./Sidebar";
import { Logo } from "./Logo";
import { YouTubeStatus } from "./YouTubeStatus";
import type { EngineState } from "../lib/engine";
import type { NavKey, ViewKey } from "../lib/navigation";
import { VIEW_TITLES } from "../lib/navigation";

interface Props {
  nav: NavKey;
  view: ViewKey;
  engine: EngineState;
  engineMessage: string | null;
  onNavigate: (key: NavKey) => void;
  onRetryEngine: () => void;
  actions?: ReactNode;
  children: ReactNode;
}

const APP_VERSION = "0.1.0";

export function AppShell({
  nav,
  view,
  engine,
  engineMessage,
  onNavigate,
  onRetryEngine,
  actions,
  children,
}: Props) {
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Pular para o conteúdo
      </a>
      <Sidebar active={nav} onNavigate={onNavigate} version={APP_VERSION} />

      <div className="workspace">
        <header className="topbar">
          <div className="topbar__context">
            <span className="topbar__mobile-brand">
              <Logo compact />
            </span>
            <span>Workspace</span>
            <ChevronRight size={13} aria-hidden="true" />
            <span className="topbar__title">{VIEW_TITLES[view]}</span>
          </div>
          <div className="topbar__actions">
            {actions}
            <EngineStatusPill
              state={engine}
              message={engineMessage}
              onRetry={onRetryEngine}
            />
          </div>
        </header>

        <main className="content" id="main-content" tabIndex={-1}>
          {/* A key troca a cada tela, então a transição roda na navegação. */}
          <div className="content__inner" key={view}>
            {children}
            <YouTubeStatus />
          </div>
        </main>
      </div>
    </div>
  );
}
