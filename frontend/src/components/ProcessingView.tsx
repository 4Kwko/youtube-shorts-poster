import { Check, Circle, Film, X } from "lucide-react";

import { SettingsSummary } from "./SettingsSummary";
import { STAGES, STAGE_LABELS, stageStates } from "../lib/stages";
import type { Video } from "../lib/types";

interface Props {
  video: Video | null;
  error: string | null;
  onRestart: () => void;
}

export function ProcessingView({ video, error, onRestart }: Props) {
  const failed = video?.status === "failed" || video?.status === "cancelled";
  const states = video ? stageStates(video) : null;
  const progress = video?.progress ?? 0;

  return (
    <section className="processing">
      <div className="processing__preview">
        <Film size={40} aria-hidden="true" />
      </div>

      <div className="panel processing__panel">
        <header className="processing__heading">
          <h1>{failed ? "Não foi possível processar" : "Processando vídeo"}</h1>
          {video?.title && <p className="processing__subject">{video.title}</p>}
          {video && <SettingsSummary settings={video.settings} />}
        </header>

        {failed ? (
          <div className="processing__failure">
            <p className="message message--error">
              {video?.error_message ?? "O processamento foi interrompido."}
            </p>
            <button type="button" className="button button--primary" onClick={onRestart}>
              Voltar ao início
            </button>
          </div>
        ) : (
          <>
            <ol className="pipeline">
              {STAGES.map((stage) => {
                const state = states?.[stage] ?? "pending";
                return (
                  <li key={stage} className={`pipeline__step pipeline__step--${state}`}>
                    <span className="pipeline__marker" aria-hidden="true">
                      {state === "done" && <Check size={15} />}
                      {state === "current" && <span className="pipeline__pulse" />}
                      {state === "pending" && <Circle size={9} />}
                      {state === "failed" && <X size={15} />}
                    </span>
                    {STAGE_LABELS[stage]}
                  </li>
                );
              })}
            </ol>

            <div className="progress">
              <div className="progress__track">
                <div
                  className="progress__bar"
                  style={{ width: `${progress}%` }}
                  role="progressbar"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              <div className="progress__meta">
                <span>{video?.current_stage ?? "Aguardando o motor"}</span>
                <span>{progress}%</span>
              </div>
            </div>

            {error && <p className="message message--warn">{error}</p>}
          </>
        )}
      </div>
    </section>
  );
}
