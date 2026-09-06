/** Formatação de tempo. Segundos podem vir como float do backend. */

/**
 * `mm:ss`, ou `h:mm:ss` a partir de uma hora.
 *
 * Trunca em vez de arredondar: 89.9s mostra 01:29, não 01:30, para o rótulo
 * nunca sugerir um instante que o clip ainda não alcançou.
 */
export function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");

  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`;
}

/** Duração legível: `1min 30s`. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";

  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;

  if (minutes === 0) return `${secs}s`;
  return secs === 0 ? `${minutes}min` : `${minutes}min ${secs}s`;
}
