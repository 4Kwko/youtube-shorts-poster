import { FileVideo, Link2, Plus, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";

import { LayoutPreview } from "./LayoutPreview";
import { SettingsSummary } from "./SettingsSummary";
import { chooseVideoFiles } from "../lib/preferences";
import {
  MAX_BATCH_VIDEOS,
  addFiles,
  addUrls,
  isValidUrl,
  removeItem,
  submitLabel,
} from "../lib/queue";
import type { QueueItem } from "../lib/queue";
import type { VideoSettings } from "../lib/settings";

interface Props {
  settings: VideoSettings;
  disabled: boolean;
  submitting: boolean;
  error: string | null;
  onSubmit: (items: QueueItem[]) => void;
  onEditSettings: () => void;
}

export function HomeView({
  settings,
  disabled,
  submitting,
  error,
  onSubmit,
  onEditSettings,
}: Props) {
  const [mode, setMode] = useState<"url" | "file">("url");
  const [input, setInput] = useState("");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const report = (skipped: number) =>
    setNotice(
      skipped > 0
        ? `${skipped} item(ns) ignorado(s): já na fila ou acima do limite de ${MAX_BATCH_VIDEOS}.`
        : null,
    );

  const full = queue.length >= MAX_BATCH_VIDEOS;

  const add = () => {
    const result = addUrls(queue, input);
    if (result.added === 0 && result.skipped === 0) {
      setNotice("Informe um link http ou https.");
      return;
    }

    setQueue(result.items);
    setInput("");
    report(result.skipped);
  };

  const pickFiles = async () => {
    const paths = await chooseVideoFiles();
    if (paths.length === 0) return;

    const result = addFiles(queue, paths);
    setQueue(result.items);
    report(result.skipped);
  };

  const canAdd = !submitting && !full && isValidUrl(input.split(/\s+/)[0] ?? "");
  const canSubmit = !disabled && !submitting && queue.length > 0;

  return (
    <section className="home">
      <div className="home__create">
        <header className="hero">
          <h1>Transforme vídeos em clips</h1>
          <p>Clips verticais prontos para Shorts, Reels e TikTok.</p>
        </header>

        <div className="source-modes" role="radiogroup" aria-label="Fonte do vídeo">
          <button
            type="button"
            role="radio"
            aria-checked={mode === "url"}
            className="source-modes__item"
            onClick={() => setMode("url")}
          >
            <Link2 size={13} aria-hidden="true" />
            Link
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === "file"}
            className="source-modes__item"
            onClick={() => setMode("file")}
          >
            <FileVideo size={13} aria-hidden="true" />
            Arquivo
          </button>
        </div>

        {mode === "file" ? (
          <button
            type="button"
            className="button button--ghost home__picker"
            disabled={submitting || full}
            onClick={() => void pickFiles()}
          >
            <FileVideo size={14} aria-hidden="true" />
            Selecionar vídeos
          </button>
        ) : (
        <div className="home__input">
          <label className="creator__field">
            <Link2 size={16} aria-hidden="true" />
            <input
              type="text"
              className="creator__input"
              placeholder="Cole um link do vídeo"
              aria-label="Link do vídeo"
              value={input}
              spellCheck={false}
              disabled={submitting || full}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") add();
              }}
            />
          </label>
          <button
            type="button"
            className="button button--ghost"
            disabled={!canAdd}
            onClick={add}
          >
            <Plus size={14} aria-hidden="true" />
            Adicionar
          </button>
        </div>
        )}

        {notice && <p className="message message--warn">{notice}</p>}
        {error && <p className="message message--error">{error}</p>}

        {queue.length > 0 && (
          <div className="queue">
            <div className="queue__head">
              <span className="queue__label">
                Fila · {queue.length}/{MAX_BATCH_VIDEOS}
              </span>
              {queue.length > 1 && (
                <button
                  type="button"
                  className="queue__clear"
                  disabled={submitting}
                  onClick={() => setQueue([])}
                >
                  Limpar fila
                </button>
              )}
            </div>

            <ol className="queue__items">
              {queue.map((item, index) => (
                <li key={item.id} className="queue__item">
                  <span className="queue__index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="queue__kind" aria-hidden="true">
                    {item.kind === "file" ? <FileVideo size={12} /> : <Link2 size={12} />}
                  </span>
                  <span className="queue__url" title={item.value}>
                    {item.label}
                  </span>
                  <button
                    type="button"
                    className="button button--icon"
                    aria-label={`Remover ${item.label} da fila`}
                    disabled={submitting}
                    onClick={() => setQueue((current) => removeItem(current, item.id))}
                  >
                    <X size={14} />
                  </button>
                </li>
              ))}
            </ol>
          </div>
        )}

        <button
          type="button"
          className="button button--primary creator__submit"
          disabled={!canSubmit}
          onClick={() => onSubmit(queue)}
        >
          {submitting ? "Enviando" : submitLabel(queue.length)}
        </button>
      </div>

      <aside className="home__preview">
        <LayoutPreview settings={settings} />
        <SettingsSummary settings={settings} />
        <button type="button" className="button button--ghost" onClick={onEditSettings}>
          <SlidersHorizontal size={14} aria-hidden="true" />
          Editar configurações
        </button>
      </aside>
    </section>
  );
}
