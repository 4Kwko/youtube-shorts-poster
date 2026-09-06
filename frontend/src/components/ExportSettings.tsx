import { FolderOpen } from "lucide-react";

import { Field, Segmented, Toggle } from "./controls";
import { chooseOutputDirectory, shortenPath } from "../lib/preferences";
import { FILENAME_OPTIONS } from "../lib/settings";
import type { VideoSettings } from "../lib/settings";

interface Props {
  value: VideoSettings;
  disabled: boolean;
  onChange: (patch: Partial<VideoSettings>) => void;
}

/**
 * Exportação: pasta de saída, nome dos arquivos e o que fazer ao concluir.
 *
 * A pasta só muda pelo diálogo nativo — não existe campo de caminho livre.
 */
export function ExportSettings({ value, disabled, onChange }: Props) {
  const pick = async () => {
    const chosen = await chooseOutputDirectory(value.output_directory);
    if (chosen) onChange({ output_directory: chosen });
  };

  return (
    <>
      <Field label="Pasta de saída">
        <div className="folder">
          <span className="folder__path" title={value.output_directory ?? undefined}>
            {shortenPath(value.output_directory)}
          </span>
          <button
            type="button"
            className="button button--ghost folder__button"
            disabled={disabled}
            onClick={() => void pick()}
          >
            <FolderOpen size={13} aria-hidden="true" />
            Alterar
          </button>
        </div>
      </Field>

      {value.output_directory && (
        <>
          <Field label="Nome dos arquivos">
            <Segmented
              label="Nome dos arquivos"
              value={value.filename_pattern}
              options={FILENAME_OPTIONS}
              disabled={disabled}
              onChange={(pattern) => onChange({ filename_pattern: pattern })}
            />
          </Field>

          <Toggle
            label="Abrir pasta ao concluir"
            checked={value.open_output_folder}
            disabled={disabled}
            onChange={(checked) => onChange({ open_output_folder: checked })}
          />
        </>
      )}

      <Toggle
        label="Manter vídeo original"
        checked={value.keep_original}
        disabled={disabled}
        onChange={(checked) => onChange({ keep_original: checked })}
      />
    </>
  );
}
