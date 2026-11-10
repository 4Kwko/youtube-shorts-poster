# SignalCut — referência técnica

[Voltar ao README](../README.md)

Detalhes de arquitetura, API, worker e processamento de mídia. Para visão geral, instalação e estado do projeto, veja o [README](../README.md).

## Estrutura e decisões

```
backend/            API FastAPI
  app/
    main.py         application factory + entrypoint ASGI
    api/            rotas HTTP e dependências
    core/           config, logging, erros, middleware
    models/         modelos persistidos no banco
    schemas/        contratos de entrada/saída (Pydantic)
    services/       regras de negócio, sem dependência de HTTP
      media/        interação com FFmpeg/FFprobe (detecção, runner, probe)
      ingest/       importação de vídeo por URL (validação, providers, yt-dlp)
    cli/            comandos de operação e diagnóstico
    utils/          helpers sem framework
frontend/           Aplicativo desktop (Tauri v2 + React + TypeScript + Vite)
  src/              Interface: componentes, hooks e cliente de API
  src-tauri/        Shell nativo (janela, CSP, bundle Windows)
storage/            mídia gerada em runtime — não versionada
tests/              testes do backend
pyproject.toml      dependências, ruff, mypy e pytest (raiz do repo)
```

Decisões que valem registrar:

- **`pyproject.toml` na raiz**, não em `backend/`. `tests/` é um diretório de topo (conforme pedido), então a configuração de pytest/ruff/mypy precisa enxergar backend e testes ao mesmo tempo. `pythonpath = ["backend"]` faz o pacote `app` ser importável sem hacks de `sys.path`.
- **Application factory** (`create_app`). Testes montam instâncias isoladas com settings próprias, sem depender de estado global de import.
- **Settings em `app.state`**, lidas pelas rotas via `Depends`. O singleton cacheado (`get_settings()`) só é usado no bootstrap.

## Qualidade

```bash
pytest                          # testes
ruff check backend tests        # lint
ruff format backend tests       # formatação
mypy backend tests              # type checking (strict)
```

## Variáveis de ambiente

Todas listadas em `.env.example`. Resumo:

| Variável | Padrão | Função |
|---|---|---|
| `APP_NAME` | `clipper-api` | Nome exibido nas docs e no `/health` |
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production` |
| `DEBUG` | `false` | Reservado para verbosidade extra |
| `API_PREFIX` | `/api/v1` | Prefixo das rotas versionadas |
| `CORS_ORIGINS` | `http://localhost:3000` | Origens permitidas, separadas por vírgula |
| `LOG_LEVEL` | `INFO` | Nível do logger raiz |
| `LOG_FORMAT` | `json` | `json` (produção) ou `text` (dev) |
| `FFPROBE_TIMEOUT_SECONDS` | `30` | Timeout das chamadas ao ffprobe |
| `MAX_VIDEO_DURATION_SECONDS` | `10800` | Duração máxima aceita na ingestão |
| `MAX_VIDEO_FILE_SIZE_BYTES` | `2147483648` | Tamanho máximo do arquivo baixado |
| `MAX_VIDEO_HEIGHT` | `1080` | Altura máxima solicitada ao provedor |
| `DOWNLOAD_TIMEOUT_SECONDS` | `1800` | Relógio de parede do download inteiro |
| `DOWNLOAD_SOCKET_TIMEOUT_SECONDS` | `30` | Timeout de socket do yt-dlp |
| `DOWNLOAD_RETRIES` | `3` | Tentativas por download/fragmento |
| `STORAGE_ROOT` | `storage` | Raiz da mídia gerada |
| `DATABASE_URL` | `sqlite:///./storage/app.db` | Conexão do banco (SQLAlchemy e Alembic) |

`.env` está no `.gitignore`. Nenhum segredo entra no código.

## Convenções da API

Toda resposta de erro usa o mesmo envelope, sem stack trace nem caminho interno:

```json
{
  "error": { "code": "not_found", "message": "Vídeo não encontrado.", "details": {} },
  "request_id": "eb7aa9b1-876a-4b6f-aa7d-3cce9c8eaab8"
}
```

O `request_id` também volta no header `X-Request-ID` e aparece em todas as linhas de log da requisição — é o identificador para correlacionar cliente e servidor ao investigar um problema. Se o cliente enviar `X-Request-ID`, ele é reaproveitado apenas quando for um UUID válido.

Falhas esperadas herdam de `AppError` (`backend/app/core/errors.py`) e carregam um `code` estável para o frontend tratar programaticamente. Falhas inesperadas viram `500 internal_error` opaco, com a exceção completa registrada no log.

## Banco de dados

Schema versionado com Alembic. `alembic.ini` fica na raiz; as migrations em
`backend/alembic/versions/`. A URL vem de `DATABASE_URL`, nunca do `.ini`.

```bash
alembic upgrade head          # aplica as migrations
alembic revision --autogenerate -m "descrição"
alembic check                 # falha se os modelos divergirem do schema
```

Sessão: não há sessão global. Quem precisa do banco abre `session_scope()`
(`app/db/session.py`), que commita no fim do bloco e faz rollback em qualquer
exceção. Os repositories (`app/repositories/`) só fazem `flush()` — commit é
sempre decisão de quem abriu o escopo.

## Smoke test

`scripts/smoke_pipeline.py` valida o caminho completo (POST → worker → storage →
ffprobe → metadata) contra a API real. A URL vem de `SMOKE_VIDEO_URL`: baixar
vídeo de terceiros depende de direito de uso, então quem roda escolhe. Não faz
parte da suíte automatizada — usa rede.

```bash
SMOKE_VIDEO_URL="https://..." python scripts/smoke_pipeline.py
```

`scripts/smoke_whisper.py` faz o equivalente para a transcrição: carrega o
modelo de verdade e confere carregamento lazy, cache, word timestamps e
timestamps crescentes. Baixa o modelo na primeira execução, então também fica
fora da suíte.

```bash
WHISPER_MODEL=tiny python scripts/smoke_whisper.py [audio.mp4]
```

> **Validação em 10/11/2026:** executado com o modelo `tiny` real em um clone limpo
> (Windows 11, Python 3.12.10): carregamento lazy, cache e normalização do resultado
> passaram. Para isso foi necessário limitar `av<19` no `pyproject.toml`; com o PyAV 19
> o `faster-whisper` 1.2.1 falha ao abrir o arquivo de áudio.

## API

Prefixo `/api/v1`. `/health` fica fora do versionamento.

| Rota | O que faz |
|---|---|
| `POST /api/v1/videos` | Valida a URL, cria `Video` + `Job(ingest)` e devolve `202` |
| `GET /api/v1/videos/{id}` | Estado e metadata do vídeo |
| `GET /api/v1/videos/{id}/jobs` | Jobs do vídeo, por ordem de criação |
| `GET /api/v1/videos/{id}/transcript` | Segmentos e timestamps por palavra |
| `GET /api/v1/videos/{id}/clips` | Clips do vídeo, por `sequence` (vazio antes do clipping) |
| `GET /api/v1/clips/{id}` | Dados de um clip (inclui `media_url`/`download_url`) |
| `GET /api/v1/clips/{id}/media` | Reproduz o render final; suporta HTTP Range |
| `GET /api/v1/clips/{id}/download` | Mesmo arquivo como `attachment` |

`POST` não baixa nada: ele só registra a intenção. O worker descobre o job
`queued` e executa. Video e Job são criados na mesma transação da requisição,
então uma falha no meio não deixa Video órfão.

`/media` e `/download` servem o render a partir do `rendered_file_key` gravado
no banco — o cliente nunca informa caminho. Leitura em blocos de 512 KiB, com
`Range` para seek: 206 com `Content-Range` quando há intervalo, 200 quando não,
416 (com `bytes */tamanho`) quando o intervalo está fora do arquivo. Header
malformado é ignorado e vira 200, como manda a RFC 9110. O nome do download vem
só do `sequence` (`clip-001.mp4`); título do provedor nunca entra em nome de
arquivo.

Respostas usam schemas Pydantic explícitos (`schemas/video.py`, `schemas/job.py`),
nunca o objeto ORM — é o que mantém `source_file_key` e qualquer referência de
disco fora da API.

## Jobs e worker

Fluxo: `Job` criado no banco → `JobQueue` → worker → `IngestService` → estado
gravado de volta em `Job` e `Video`.

```bash
python -m app.cli.enqueue_video "<URL>"   # cria Video + Job queued
python -m app.worker                      # processa a fila
```

| Módulo | Responsabilidade |
|---|---|
| `jobs/queue.py` | Protocolo `JobQueue` + `InMemoryJobQueue` |
| `jobs/handlers.py` | Registry `JobType -> handler`: `ingest`, `transcribe`, `clip`, `render` |
| `jobs/worker.py` | Loop sequencial, recuperação e classificação de falha |
| `app/worker.py` | Entrypoint `python -m app.worker` |

Pontos que valem saber antes de mexer:

- **A fila é só um índice; o banco é a fonte de verdade.** `InMemoryJobQueue`
  vive em um processo e não sobrevive a restart. Por isso o worker varre a
  tabela `jobs` ao iniciar e sempre que fica ocioso — é assim que ele enxerga
  o que a CLI enfileirou em outro processo. Trocar por Redis é substituir essa
  classe.
- **Nenhuma Session global.** O handler recebe a *factory* e abre transações
  curtas, uma por passo, para que o progresso fique visível durante o download.
- **Claim atômico.** O worker não "encontra e depois marca": `JobRepository.claim`
  faz `UPDATE ... WHERE status = 'queued'` e só executa o handler se `rowcount`
  for 1. A tentativa é consumida aí, uma única vez. Perder o claim não é erro —
  o job simplesmente é de outro worker.
- **Jobs órfãos em `running`** (crash do worker) voltam para `queued` na
  inicialização se ainda houver tentativa; caso contrário são encerrados como
  `failed` junto com o Video.
- **Retry sem backoff, limitado por `max_attempts`.** Só erro técnico
  (`status_code >= 500`) é retentado; erro permanente — vídeo indisponível,
  tipo de job sem handler — falha de vez.

## Transcrição

Pipeline: `ingest → transcribe → clip → render`.

- O **vídeo original é transcrito uma única vez**, com `word_timestamps=True`.
  Transcrever clips separadamente custaria N execuções do Whisper e daria
  timestamps rebaseados; aqui eles já ficam no eixo do vídeo inteiro.
- `transcription/backend.py` é o único módulo que importa `faster_whisper`, e o
  import acontece **dentro** da função de carga: a aplicação sobe sem a
  biblioteca instalada e sem modelo baixado, e a falha vira
  `transcription_model_unavailable`, não erro de import.
- O modelo é carregado sob demanda e cacheado por processo
  (`_model_cache`, chaveado por modelo/device/compute_type), então o worker
  paga o carregamento uma vez e reutiliza entre jobs.
- **Sem WAV intermediário:** o faster-whisper decodifica o container com o
  FFmpeg embutido; extrair áudio antes seria I/O e disco sem ganho.
- O texto vai para `storage/transcripts/{video_id}/transcript.json` (UTF-8 com
  acentos, campo `version`), escrito em `.tmp` + rename para nunca deixar JSON
  truncado. O banco guarda só metadata em `transcripts` (1:1 com Video,
  `video_id` unique) e a chave relativa — nunca caminho absoluto.
- Falha remove o JSON parcial e não cria o job de clipping. Retry sobrescreve
  deterministicamente e faz upsert do registro.
- Estados novos: `TRANSCRIBING` / `TRANSCRIBED`.

## Clipping

Modo `fixed`: o vídeo é fatiado em trechos sequenciais de `DEFAULT_CLIP_DURATION_SECONDS`
(90s por padrão), o último podendo ser menor. A conversão para 9:16 acontece na etapa de render.

- `clipping/intervals.py` calcula os intervalos — função pura, sem FFmpeg.
  Um resto menor que 1s é absorvido pelo clip anterior em vez de virar arquivo.
- **A etapa `clip` não gera arquivo.** Ela só calcula intervalos e grava os
  registros — o corte acontece junto com a conversão vertical, numa passagem
  só de FFmpeg por clip. Gerar um clip horizontal intermediário custaria dois
  encodes por clip. O job de clipping é rápido mesmo para vídeo de horas.
- `Clip.source_file_key` fica nulo no fluxo atual (a coluna já era nullable, sem
  migration). Continua existindo para intermediários opcionais; `FixedClipper`
  segue disponível e testado, mas fora do caminho padrão.
- Reexecutar o job apaga os registros da tentativa anterior, então retry não
  duplica `sequence`.
- **Encadeamento automático:** ao concluir a ingestão, o handler cria um
  `Job(clip)` na *mesma transação* que grava a metadata — não existe estado com
  ingestão concluída e clipping nunca enfileirado. O handler de ingestão não
  chama o de clipping; quem executa é o worker, no ciclo seguinte.
  `JobRepository.create_if_absent` impede duplicata: só cria se não houver job
  do mesmo tipo `queued`, `running` ou `succeeded` para aquele vídeo.
- **Novo estado `VideoStatus.CLIPPED`**: o vídeo fica `processing` durante o
  corte e termina em `clipped`. Não vai para `completed` porque ainda faltam
  transcrição e renderização. O enum é VARCHAR na migration, então o valor novo
  não exigiu migration.

## Legendas

Pipeline: `ingest → transcribe → clip → render`, com o `.ass` gerado dentro do
render.

- `subtitles/mapping.py` recorta o transcript global para o intervalo do clip:
  timestamps recomeçam em zero, nada fica negativo nem passa da duração, e o
  transcript global nunca é mutado. Segmento cortado ao meio tem o texto
  reconstruído a partir das palavras que sobraram — usar o texto original
  traria fala que não está no clip.
- `subtitles/chunking.py` agrupa palavras em blocos de 2–5, quebrando por
  pontuação, pausa audível (`SUBTITLE_PAUSE_BREAK_SECONDS`) e tamanho de linha.
  Bloco curto demais é esticado até `SUBTITLE_MIN_DURATION_SECONDS` sem
  sobrepor o seguinte.
- `subtitles/ass.py` escreve o ASS em `PlayResX/Y` 1080x1920 com o preset
  `bold`. `MarginV` alto tira a legenda da faixa onde TikTok/Reels desenham UI.
  **Todo texto é escapado** (`\`, `{`, `}`, quebras de linha): transcrição
  nunca vira override tag do libass.
- Arquivos em `storage/subtitles/{video_id}/{sequence}.ass`, regeneráveis a
  partir do transcript — sobrescrever é sempre seguro. Não expostos pela API.
- Clip sem fala renderiza normalmente, só sem legenda.

## Renderização vertical

Cada clip vira um MP4 1080x1920 (H.264/AAC, `yuv420p`). O layout padrão é
`blurred_4_3`: o vídeo entra em 4:3 no centro, sobre uma cópia dele mesmo
ampliada e desfocada preenchendo o canvas.

- `rendering/filters.py` decide o enquadramento em `plan_layout()` (função pura
  sobre as dimensões da origem) e monta o filtergraph em `build_filtergraph()`:
  - **16:9 ou mais largo:** crop central das laterais até 4:3 → foreground
    1080x810 centralizado, fundo desfocado.
  - **entre 1:1 e 4:3:** sem crop, só redução. Quadrado vira 1080x1080.
  - **vertical:** preenche o canvas como no `center_crop`, sem fundo. Forçar
    4:3 aqui cortaria o que o vídeo tem de útil.
  Nunca há stretch: a proporção do foreground é sempre a do recorte.
- `center_crop` continua disponível como opção (`VerticalLayout.CENTER_CROP`),
  só não é mais o padrão.
- O fundo é desfocado a 270x480 e só depois ampliado para 1080x1920: o `gblur`
  custa proporcional à área, e o detalhe já foi destruído pelo desfoque.
- Parâmetros de encoding centralizados em `VIDEO_ENCODING_ARGS`/
  `AUDIO_ENCODING_ARGS` — otimizar depois é mexer num lugar só.
- A origem é sempre o vídeo original (`Video.source_file_key`, em
  `storage/downloads/`), recortado por `-ss`/`-t` na mesma invocação do filtro
  vertical. Fundo, foreground, overlay e burn-in da legenda ficam no mesmo
  `filter_complex` — **um encode por clip**, com `split` duplicando a origem em
  vez de gerar arquivo intermediário. O original nunca é sobrescrito; a saída vai para
  `storage/renders/{video_id}/{sequence}.mp4` (`rendered_file_key`).
- Falha remove a saída parcial. No retry, clips já `rendered` com arquivo em
  disco são pulados; o resto é refeito deterministicamente sobre o mesmo nome.
- **`VideoStatus.RENDERED`**: `clipped → processing → rendered`. É o estado final
  do processamento; a publicação no YouTube tem fila própria.
- Concluir o clipping cria `Job(render)` na mesma transação, com a mesma
  proteção contra duplicata do encadeamento anterior.

## Camada de mídia

`backend/app/services/media/` isola tudo que fala com FFmpeg e FFprobe:

| Módulo | Responsabilidade |
|---|---|
| `binaries.py` | Detecta os binários via `shutil.which`, lê versão, cacheia por 30s |
| `runner.py` | Único ponto que executa subprocesso: lista de argumentos, `shell=False`, timeout obrigatório |
| `probe.py` | Monta os argumentos do ffprobe e converte o JSON em `MediaInfo` |
| `errors.py` | Exceções de mídia, herdando de `AppError` |

Regras que valem para qualquer código novo nessa camada:

- Comandos são **listas de argumentos**. Nunca string, nunca `shell=True`.
- Todo comando tem timeout. Sem exceção.
- `stderr` do processo vai para o log (truncado) e **nunca** para a resposta HTTP.
- A API não recebe caminho de arquivo. Recebe subdiretório de storage + nome, e `app/utils/paths.py` é o único lugar que resolve isso em caminho absoluto, provando que o resultado não escapou da raiz.

Uso interno:

```python
from app.services.media import probe_storage_file

info = probe_storage_file(settings, "downloads", "video.mp4")
info.duration_seconds, info.width, info.height, info.fps
info.video_codec, info.audio_codec, info.bitrate_bps, info.container
```

Todos os campos de `MediaInfo` são opcionais: o ffprobe legitimamente omite parte deles conforme o container. Trate a ausência em vez de assumir um default.

## Ingestão de vídeo

`backend/app/services/ingest/` importa um vídeo por URL para o storage interno.

| Módulo | Responsabilidade |
|---|---|
| `urls.py` | Valida a URL e resolve o provider. Função pura, sem rede |
| `providers.py` | Allowlist de hosts e extractors permitidos por provider |
| `downloader.py` | Protocolo `VideoDownloader` — a fronteira que permite trocar de mecanismo |
| `ytdlp.py` | Única parte do projeto que importa `yt_dlp` |
| `metadata.py` | Normalização pura da metadata externa |
| `service.py` | Orquestra: valida, gera ID, recusa cedo, baixa, confere, limpa |
| `errors.py` | Erros de ingestão, herdando de `AppError` |

Garantias que valem para código novo aqui:

- **A URL do usuário nunca vira requisição fora do yt-dlp.** Antes disso ela passa por `validate_video_url`: só `http`/`https`, sem credenciais, sem host por IP, sem porta fora de 80/443, e o host precisa estar na allowlist. `allowed_extractors` impede o extractor genérico do yt-dlp de aceitar host arbitrário.
- **O usuário não escolhe o caminho de saída.** O ID interno é um UUID4; o arquivo é sempre `storage/downloads/{video_id}/source.{ext}`. O título do provedor é sanitizado só para exibição e nunca toca o path.
- **O caminho que o yt-dlp anuncia é dado não confiável**: só é seguido se cair dentro do workspace do vídeo.
- **Limite de tamanho é conferido no disco**, não só na metadata prévia. Estourou, o workspace inteiro é removido.
- **Qualquer falha após criar o workspace remove o diretório.** Não fica download parcial ocupando storage.

### CLI

```bash
python -m app.cli.import_video --check-only "<URL>"   # só valida, não baixa
python -m app.cli.import_video "<URL>"                # importa
```

Rode a partir da raiz do repo, com `PYTHONPATH=backend`.


## Checklist manual ponta a ponta

Rodando apenas `npm run tauri dev`, sem nenhum processo Python iniciado à mão:

- [ ] status passa por **Iniciando motor…** e chega em **Motor pronto**
- [ ] o terminal mostra `[migrations]`, `[backend]` e `[worker]`
- [ ] colar URL de um vídeo que você tenha direito de baixar
- [ ] `Gerar clips` responde de imediato (POST 202, sem travar a interface)
- [ ] etapas avançam: Importando → Transcrevendo → Criando clips → Renderizando
- [ ] percentual sobe e o título do vídeo aparece quando conhecido
- [ ] estado final `rendered`, tela de resultados com os clips
- [ ] `<video>` reproduz com áudio
- [ ] arrastar a barra (seek) funciona sem recarregar o clip inteiro
- [ ] legenda aparece queimada, com acentos corretos
- [ ] duração de cada clip é 90s, e o último pode ser menor
- [ ] botão Download entrega o `.mp4` como `clip-000.mp4`
- [ ] fechar o app e confirmar no Gerenciador de Tarefas que nenhum
      `python.exe` sobrou (`Get-Process python -ErrorAction SilentlyContinue`)

Falhou? O terminal do Tauri concentra o log dos três processos, com
`request_id` e `error_code`.
