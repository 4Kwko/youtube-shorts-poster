import { summaryItems } from "../lib/settings";
import type { VideoSettings } from "../lib/settings";

interface Props {
  settings: VideoSettings;
}

/** Resumo compacto: duração, layout e legenda. */
export function SettingsSummary({ settings }: Props) {
  return (
    <ul className="summary-tags">
      {summaryItems(settings).map((item) => (
        <li key={item.label}>
          {item.color && (
            <span
              className="summary-tags__swatch"
              style={{ background: item.color }}
              aria-hidden="true"
            />
          )}
          {item.label}
        </li>
      ))}
    </ul>
  );
}
