import {
  ArrowLeft,
  AudioLines,
  Check,
  Circle,
  Download,
  Film,
  Layers,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { SettingsSummary } from "./SettingsSummary";
import { Badge, Button, Progress, TimelineArt } from "./ui";
import { STAGES, STAGE_LABELS, stageStates } from "../lib/stages";
import type { StageId } from "../lib/stages";
import type { Video } from "../lib/types";

interface Props {
  video: Video | null;
  error: string | null;
  onRestart: () => void;
}
const ICONS: Record<StageId, LucideIcon> = {
  importing: Download,
  transcribing: AudioLines,
  clipping: Layers,
  rendering: Film,
};
const descriptions: Record<StageId, string> = {
  importing: "Preparando o arquivo de origem",
  transcribing: "Convertendo a fala em texto",
  clipping: "Separando os intervalos do vídeo",
  rendering: "Compondo vídeo, áudio e legendas",
};
export function ProcessingView({ video, error, onRestart }: Props) {
  const failed = video?.status === "failed" || video?.status === "cancelled";
  const states = video ? stageStates(video) : null;
  const progress = video?.progress ?? 0;
  const current = STAGES.find((stage) => states?.[stage] === "current");
  const counter = video?.current_stage?.match(/\b\d+\/\d+\b/)?.[0];
  const stageLabel = current ? STAGE_LABELS[current] : "Aguardando o motor";
  return (
    <section className="processing">
      <header className="page-heading">
        <div>
          <span className="eyebrow">CENTRAL DE PROCESSAMENTO</span>
          <h1>
            {failed
              ? "O processamento foi interrompido"
              : "Seu vídeo está em produção."}
          </h1>
          <p className="processing__subject">
            {video?.title ?? "Preparando o projeto"}
          </p>
        </div>
        <Button variant="ghost" onClick={onRestart}>
          <ArrowLeft size={15} aria-hidden="true" />
          Voltar
        </Button>
      </header>
      <div className="processing__workspace">
        <aside className="processing__preview panel">
          <div className="processing__art">
            <TimelineArt />
            <span className="mono">
              {failed ? "INTERROMPIDO" : "PROCESSAMENTO LOCAL"}
            </span>
          </div>
          <div className="processing__readout">
            <span>Progresso do projeto</span>
            <strong className="mono">
              {progress}
              <small>%</small>
            </strong>
            <Badge tone={failed ? "danger" : "success"}>
              {failed
                ? "Requer atenção"
                : current
                  ? STAGE_LABELS[current]
                  : "Aguardando"}
            </Badge>
          </div>
          {video && <SettingsSummary settings={video.settings} />}
        </aside>
        <div className="panel processing__panel">
          <div className="panel-heading">
            <div>
              <Layers size={16} aria-hidden="true" />
              <h2>Etapas do processamento</h2>
            </div>
            <span className="eyebrow">PIPELINE</span>
          </div>
          {!failed && (
            <ol className="pipeline" aria-label="Etapas do processamento">
              {STAGES.map((stage, index) => {
                const state = states?.[stage] ?? "pending";
                const Icon = ICONS[stage];
                return (
                  <li
                    key={stage}
                    className={`pipeline__step pipeline__step--${state}`}
                    aria-current={state === "current" ? "step" : undefined}
                  >
                    <span className="pipeline__marker" aria-hidden="true">
                      {state === "done" ? (
                        <Check size={17} />
                      ) : state === "failed" ? (
                        <X size={17} />
                      ) : (
                        <Icon size={17} />
                      )}
                    </span>
                    <span className="pipeline__body">
                      <strong>{STAGE_LABELS[stage]}</strong>
                      <small>{descriptions[stage]}</small>
                    </span>
                    <span className="pipeline__state">
                      {state === "done" ? (
                        "Concluído"
                      ) : state === "current" ? (
                        <>
                          <span className="pipeline__pulse" />
                          Em andamento
                        </>
                      ) : (
                        <span className="mono">0{index + 1}</span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {failed ? (
            <div className="processing__failure">
              <p role="alert" className="message message--error">
                {video?.error_message ?? "O processamento foi interrompido."}
              </p>
              <Button variant="secondary" onClick={onRestart}>
                Voltar ao início
              </Button>
            </div>
          ) : (
            <div className="progress">
              <Progress value={progress} label="Progresso do processamento" />
              <div className="progress__meta">
                <span>
                  <Circle size={6} fill="currentColor" aria-hidden="true" />
                  {stageLabel}
                  {counter ? ` · ${counter}` : ""}
                </span>
                <span className="mono">{progress}%</span>
              </div>
              {error && (
                <p role="alert" className="message message--warn">
                  {error}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
