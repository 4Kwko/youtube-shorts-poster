import {
  ArrowRight,
  CheckCircle2,
  FileVideo,
  Link2,
  ListVideo,
  Plus,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LayoutPreview } from "./LayoutPreview";
import { QueueItemRow } from "./QueueItemRow";
import { SettingsSummary } from "./SettingsSummary";
import { Badge, Button, TimelineArt } from "./ui";
import { chooseVideoFiles } from "../lib/preferences";
import {
  MAX_BATCH_VIDEOS,
  addFiles,
  addUrls,
  parseUrls,
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
  const [removing, setRemoving] = useState<string | null>(null);
  const removalTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(removalTimer.current), []);
  const locked = submitting || removing !== null;
  const full = queue.length >= MAX_BATCH_VIDEOS;
  const urls = parseUrls(input);
  const invalid = input.trim().length > 0 && urls.length === 0;
  const report = (skipped: number) =>
    setNotice(
      skipped > 0
        ? `${skipped} item(ns) ignorado(s): já na fila ou acima do limite de ${MAX_BATCH_VIDEOS}.`
        : null,
    );
  const add = () => {
    if (locked || full) return;
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
  const remove = (id: string) => {
    setRemoving(id);
    removalTimer.current = setTimeout(() => {
      setQueue((current) => removeItem(current, id));
      setRemoving(null);
    }, 140);
  };
  const canAdd = !locked && !full && urls.length > 0;
  const canSubmit = !disabled && !locked && queue.length > 0;
  return (
    <section className="home">
      <header className="page-heading home__heading">
        <div>
          <span className="eyebrow">STUDIO / NOVO PROJETO</span>
          <h1>Seu próximo corte começa aqui.</h1>
          <p>Transforme vídeos longos em clipes prontos para publicar.</p>
        </div>
        <Badge>
          <span className="signal-dot" />
          YouTube Shorts
        </Badge>
      </header>
      <div className="home__workspace">
        <div className="home__create panel">
          <div className="panel-heading">
            <div>
              <span className="panel-heading__index mono">01</span>
              <h2>Adicione seus vídeos</h2>
            </div>
            <span className="eyebrow">ATÉ 20 POR ENVIO</span>
          </div>
          <div
            className="source-modes"
            role="radiogroup"
            aria-label="Fonte do vídeo"
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
              event.preventDefault();
              const next = mode === "url" ? "file" : "url";
              setMode(next);
              const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("button");
              buttons[next === "url" ? 0 : 1]?.focus();
            }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={mode === "url"}
              className="source-modes__item"
              onClick={() => setMode("url")}
            >
              <Link2 size={15} aria-hidden="true" />
              Colar links
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={mode === "file"}
              className="source-modes__item"
              onClick={() => setMode("file")}
            >
              <FileVideo size={15} aria-hidden="true" />
              Arquivos locais
            </button>
          </div>
          {mode === "file" ? (
            <button
              type="button"
              className="home__picker"
              disabled={locked || full}
              onClick={() => void pickFiles()}
            >
              <Upload size={25} aria-hidden="true" />
              <strong>Selecionar vídeos</strong>
              <span>Escolha um ou mais arquivos do computador</span>
            </button>
          ) : (
            <div className="home__input">
              <label htmlFor="video-urls" className="field-label">
                Link do vídeo
              </label>
              <div
                className={`creator__field ${invalid ? "creator__field--invalid" : urls.length ? "creator__field--valid" : ""}`}
              >
                <Link2 size={19} aria-hidden="true" />
                <textarea
                  id="video-urls"
                  className="creator__input"
                  placeholder="Cole um link do YouTube ou vários links…"
                  aria-describedby="url-feedback"
                  aria-invalid={invalid || undefined}
                  value={input}
                  rows={2}
                  spellCheck={false}
                  disabled={locked || full}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      add();
                    }
                  }}
                />
              </div>
              <div className="creator__input-footer">
                <p
                  id="url-feedback"
                  className={`input-feedback ${invalid ? "input-feedback--invalid" : urls.length ? "input-feedback--valid" : ""}`}
                  aria-live="polite"
                >
                  {invalid ? (
                    <>
                      <TriangleAlert size={13} aria-hidden="true" />
                      Use um link http ou https válido.
                    </>
                  ) : urls.length ? (
                    <>
                      <CheckCircle2 size={13} aria-hidden="true" />
                      {urls.length === 1
                        ? "Link válido"
                        : `${urls.length} links identificados`}
                    </>
                  ) : (
                    <>Cole vários links separados por espaço ou linha.</>
                  )}
                </p>
                <Button variant="secondary" disabled={!canAdd} onClick={add}>
                  <Plus size={15} aria-hidden="true" />
                  Adicionar à fila
                </Button>
              </div>
            </div>
          )}
          {notice && (
            <p role="status" className="message message--warn">
              {notice}
            </p>
          )}
          {error && (
            <p role="alert" className="message message--error">
              {error}
            </p>
          )}
          <div className="queue">
            <div className="queue__head">
              <h3>
                <ListVideo size={16} aria-hidden="true" />
                Fila de criação{" "}
                <span className="queue__count mono" aria-live="polite">
                  {queue.length} / {MAX_BATCH_VIDEOS}
                </span>
              </h3>
              {queue.length > 0 && (
                <Button
                  variant="ghost"
                  className="queue__clear"
                  disabled={locked}
                  onClick={() => {
                    setQueue([]);
                    setNotice(null);
                  }}
                >
                  Limpar fila
                </Button>
              )}
            </div>
            {queue.length === 0 ? (
              <div className="queue__empty">
                <TimelineArt />
                <p>Sua fila começa com um vídeo.</p>
                <span>
                  Adicione links ou arquivos para preparar seus cortes.
                </span>
              </div>
            ) : (
              <ol className="queue__items" aria-label="Vídeos na fila">
                {queue.map((item, index) => (
                  <QueueItemRow
                    key={item.id}
                    item={item}
                    index={index}
                    disabled={locked}
                    submitting={submitting}
                    removing={removing === item.id}
                    onRemove={() => remove(item.id)}
                  />
                ))}
              </ol>
            )}
          </div>
          <div className="creator__footer">
            <span className="creator__hint">
              {disabled
                ? "Aguardando conexão com o motor local"
                : full
                  ? "Limite de 20 vídeos atingido"
                  : "Tudo pronto? Gere seus projetos."}
            </span>
            <Button
              variant="primary"
              className="creator__submit"
              loading={submitting}
              disabled={!canSubmit}
              onClick={() => onSubmit(queue)}
            >
              {!submitting && <Sparkles size={16} aria-hidden="true" />}
              {submitting ? "Enviando" : submitLabel(queue.length)}
              {!submitting && <ArrowRight size={16} aria-hidden="true" />}
            </Button>
          </div>
        </div>
        <aside className="home__preview panel">
          <div className="panel-heading">
            <div>
              <span className="panel-heading__index mono">02</span>
              <h2>Seu enquadramento</h2>
            </div>
            <Badge>9:16</Badge>
          </div>
          <div className="preview-stage">
            <span className="preview-stage__label mono">OUTPUT / SHORT</span>
            <LayoutPreview settings={settings} />
            <span className="preview-stage__caption">Ilustração do layout</span>
          </div>
          <div className="preview-settings">
            <SettingsSummary settings={settings} />
            <Button variant="ghost" onClick={onEditSettings}>
              <SlidersHorizontal size={14} aria-hidden="true" />
              Ajustar configurações
              <ArrowRight size={14} aria-hidden="true" />
            </Button>
          </div>
        </aside>
      </div>
    </section>
  );
}
