# Organização do Clipper

- `backend/app/api/routes/`: rotas HTTP, incluindo conexão e opções do YouTube.
- `backend/app/services/youtube.py`: fila durável, validação de Shorts e uploads.
- `backend/app/services/youtube_auth.py`: login Google Desktop e validação do canal.
- `backend/app/services/youtube_preferences.py`: descrição, hashtags e pausa persistidas.
- `backend/app/services/rendering/`, `clipping/`, `transcription/`: processamento de mídia.
- `frontend/src/features/youtube/`: painel e estilos da publicação de Shorts.
- `frontend/src/components/`: componentes compartilhados; `src/lib/`: acesso à API.
- `frontend/src-tauri/`: inicialização do desktop e gerenciamento do motor local.
- `scripts/`: conexão pelo terminal, desenvolvimento e build Windows.
- `tests/`: testes do backend. Testes do frontend ficam próximos dos módulos.
- `assets/`: arquivos de identidade visual versionados.
- `docs/history/`: notas antigas de patches, preservadas para referência.
- `storage/`: downloads, renders, legendas, credenciais e bancos locais; não versionar.

O projeto ativo é esta pasta, `D:\Youtube Shorts Poster`. A cópia anterior em
`D:\clipper-v4\clipper-v4` permanece preservada; não misture os ambientes `.venv`.
