import type { EngineState } from "../lib/engine";
import { ENGINE_LABELS } from "../lib/engine";

interface Props {
  state: EngineState;
  message: string | null;
  onRetry: () => void;
}

export function EngineStatusPill({ state, message, onRetry }: Props) {
  return (
    <div
      className={`engine-pill engine-pill--${state}`}
      role="status"
      title={message ?? undefined}
    >
      <span className="engine-pill__dot" aria-hidden="true" />
      <span>{ENGINE_LABELS[state]}</span>
      {state === "offline" && (
        <button type="button" className="engine-pill__retry" onClick={onRetry}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}
