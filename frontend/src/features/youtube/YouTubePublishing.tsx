import { useEffect, useState } from "react";
import { api, type PublishingPreferences } from "../../lib/api";
import "./youtube.css";

type Status = Awaited<ReturnType<typeof api.youtubeStatus>>;
const states: Record<string, string> = {
  queued: "Na fila", uploading: "Enviando (se interrompido, confira o Studio)",
  uploaded: "Enviado", needs_review: "Requer atenção",
};

export function YouTubePublishing() {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<PublishingPreferences | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void api.youtubeStatus().then(value => {
        if (active) {
          setStatus(value);
          setDraft(previous => previous ?? value.preferences);
        }
      }).catch(() => { if (active) setStatus(null); });
    };
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  async function act(task: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await task();
      setStatus(await api.youtubeStatus());
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Não foi possível concluir.");
    } finally { setBusy(false); }
  }

  if (!status || !draft) return <p role="status">YouTube Shorts: aguardando o motor local…</p>;
  const connecting = status.login_state === "connecting";
  return <details className="youtube-panel">
    <summary>YouTube Shorts · {status.enabled ? "Envio automático ativo" : "Envio pausado"}</summary>
    <div className="youtube-content">
      <p>{status.connected ? `Conexão salva: ${status.channel ?? status.channel_id}` : "Conecte seu canal do YouTube."}</p>
      <p>Somente os vídeos que você escolher serão processados. Mantenha o Clipper aberto até terminar os envios.</p>
      <div className="youtube-actions">
        <button disabled={busy || connecting || !status.configured}
          onClick={() => void act(() => api.youtubeConnect(), "Conclua o login no navegador.")}>
          {connecting ? "Aguardando autorização…" : status.connected ? "Reconectar YouTube" : "Entrar com Google"}
        </button>
        <label>Importar credencial Google Desktop (.json)
          <input type="file" accept=".json,application/json" disabled={busy || connecting}
            onChange={event => {
              const file = event.target.files?.[0];
              if (file) void act(async () => {
                if (file.size > 20000) throw new Error("Selecione apenas o JSON do cliente OAuth.");
                await api.youtubeClient(await file.text());
              }, "Credencial importada. Agora clique em Entrar com Google.");
              event.target.value = "";
            }} />
        </label>
      </div>
      {status.login_error && <p role="alert">{status.login_error}</p>}
      {status.publishing_error && <p role="alert">{status.publishing_error}</p>}
      <form onSubmit={event => {
        event.preventDefault();
        void act(() => api.youtubeSavePreferences(draft), "Preferências salvas para os próximos clipes. Não precisa reiniciar.");
      }}>
        <label className="youtube-toggle"><input type="checkbox" checked={draft.enabled}
          onChange={event => setDraft({ ...draft, enabled: event.target.checked })} />
          Publicar automaticamente após renderizar</label>
        <label>Legenda fixa da postagem (descrição)
          <textarea rows={4} maxLength={4000} value={draft.description}
            placeholder="Texto que aparecerá na descrição de todos os seus Shorts"
            onChange={event => setDraft({ ...draft, description: event.target.value })} />
        </label>
        <label>Hashtags (separadas por espaços)
          <input maxLength={500} value={draft.hashtags} placeholder="#Shorts #SignalCut"
            onChange={event => setDraft({ ...draft, hashtags: event.target.value })} />
        </label>
        <label>Visibilidade
          <select value={draft.privacy} onChange={event => setDraft({ ...draft,
            privacy: event.target.value as PublishingPreferences["privacy"] })}>
            <option value="public">Público</option><option value="unlisted">Não listado</option>
            <option value="private">Privado</option>
          </select>
        </label>
        <p>Shorts: vídeo vertical ou quadrado, até 3 minutos. Arquivos fora desse padrão terão o envio bloqueado.
          As legendas faladas na imagem continuam nas configurações de renderização.</p>
        <button type="submit" disabled={busy}>Salvar preferências</button>
      </form>
      {message && <p role="status">{message}</p>}
      <h3>Publicações recentes</h3>
      {!status.uploads.length && <p>Nenhum clipe na fila ainda.</p>}
      {status.uploads.slice(-20).reverse().map(item => <div className="youtube-upload" key={item.clip_id}>
        <strong>{item.title}</strong> — {states[item.state] ?? item.state}
        {item.youtube_id && <a href={`https://www.youtube.com/shorts/${encodeURIComponent(item.youtube_id)}`}
          target="_blank" rel="noreferrer">Abrir Short</a>}
        {item.actual_privacy && <span>Visibilidade retornada: {item.actual_privacy}</span>}
        {item.error && <p role="alert">{item.error}</p>}
      </div>)}
      <p>O Google pode restringir envios a privado enquanto o projeto da API não passar por auditoria.</p>
    </div>
  </details>;
}
