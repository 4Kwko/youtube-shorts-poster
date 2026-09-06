import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Status = Awaited<ReturnType<typeof api.youtubeStatus>>;

export function YouTubeStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void api.youtubeStatus().then(value => {
        if (active) setStatus(value);
      }).catch(() => { if (active) setStatus(null); });
    };
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if (!status) return null;
  return <details style={{ marginBottom: 16 }}>
    <summary>YouTube — {!status.connected ? "Conectar canal" :
      status.enabled ? "Publicação automática ativada" : "Publicação automática desativada"}</summary>
    {!status.connected && <p>Conecte o canal seguindo docs/youtube-publishing.md.</p>}
    {status.connected && <p>Conexão salva; o canal será verificado antes de cada envio.</p>}
    {status.uploads.slice(-20).reverse().map(item => <p key={item.clip_id}>
      {item.title} — {item.state}
      {item.actual_privacy && ` (${item.actual_privacy})`}
      {item.youtube_id && ` — youtube.com/watch?v=${item.youtube_id}`}
      {item.error && ` — ${item.error}`}
    </p>)}
  </details>;
}
