/** Navegação e resolução da tela atual. Função pura, testável sem DOM. */

export type NavKey = "home" | "projects" | "settings";
export type ViewKey = NavKey | "processing" | "results";

export const NAV_ITEMS: readonly NavKey[] = ["home", "projects", "settings"];

export const NAV_LABELS: Record<NavKey, string> = {
  home: "Home",
  projects: "Projetos",
  settings: "Configurações",
};

export const VIEW_TITLES: Record<ViewKey, string> = {
  home: "Home",
  projects: "Projetos",
  settings: "Configurações",
  processing: "Processando",
  results: "Clips",
};

interface ResolveParams {
  nav: NavKey;
  videoId: string | null;
  /** Status vindo do backend; `null` enquanto o primeiro polling não voltou. */
  status: string | null;
}

/**
 * Decide qual tela mostrar.
 *
 * Um vídeo em andamento só ocupa a área principal quando a navegação está em
 * Home: assim dá para abrir Projetos ou Configurações sem perder o job, e
 * voltar para Home mostra o progresso de novo.
 */
export function resolveView({ nav, videoId, status }: ResolveParams): ViewKey {
  // Um vídeo aberto ocupa a área principal tanto na Home (recém-criado) quanto
  // em Projetos (reaberto do histórico); Configurações nunca é interrompida.
  if (nav === "settings") return nav;
  if (videoId === null) return nav;
  const done = status === "rendered" || status === "exported" || status === "completed";
  return done ? "results" : "processing";
}
