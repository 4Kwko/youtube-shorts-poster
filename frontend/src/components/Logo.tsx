interface Props {
  compact?: boolean;
}
export function Logo({ compact = false }: Props) {
  return (
    <span className="logo" aria-label="SignalCut">
      <img
        className="logo__symbol"
        src="/brand/signalcut-symbol.svg"
        alt=""
        aria-hidden="true"
      />
      {!compact && (
        <span className="logo__wordmark">
          Signal<span>Cut</span>
        </span>
      )}
    </span>
  );
}
