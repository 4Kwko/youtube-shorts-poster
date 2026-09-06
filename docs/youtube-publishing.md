# Publicação de YouTube Shorts

## Usar no SignalCut

1. Abra `SignalCut.exe` na raiz deste projeto e expanda **Publicação no YouTube**.
2. Se o canal já foi conectado pelo terminal, a conexão existente será reconhecida.
   Para conectar pela interface, importe o JSON de um cliente Google OAuth **Desktop app**
   e clique em **Entrar com Google**. A autorização acontece no navegador.
3. Use a conta do canal configurado em `YOUTUBE_CHANNEL_ID`. O SignalCut verifica esse ID
   antes de salvar uma nova conexão e antes de publicar.
4. Preencha **Legenda fixa da postagem** e **Hashtags**. Essa legenda é a descrição do
   Short; as legendas faladas na imagem são configuradas separadamente na renderização.
5. Marque **Publicar automaticamente após renderizar**, escolha a visibilidade e salve.
   As alterações são lidas pelo worker sem reiniciar. Um envio já iniciado pode terminar
   depois de pausar; os próximos envios aguardam a reativação.
6. Escolha seus vídeos e gere os cortes. Mantenha o SignalCut aberto até a fila terminar.

O texto e a visibilidade são copiados para cada clipe quando ele entra na fila. Alterações
posteriores valem para novos clipes. Renders antigos não são publicados retroativamente.

## Somente Shorts

A interface oferece cortes de 30 a 180 segundos. Os layouts 4:3/16:9 com blur preservam
o conteúdo dentro de um canvas vertical 9:16. Antes de enviar, o FFprobe verifica o
arquivo real: precisa ser quadrado ou vertical e ter duração positiva de até 180 segundos.
Arquivos incompatíveis ou que não puderem ser verificados ficam bloqueados na fila.

Não existe um endpoint separado para Shorts: o YouTube faz a classificação pelo formato
e duração. [Regras oficiais](https://support.google.com/youtube/answer/15424877).

## Conexão e falhas

Ative YouTube Data API v3 no projeto Google Cloud. Em modo Testing, cadastre a conta do
canal como usuário de teste; a autorização pode exigir reconexão após sete dias.
O painel mostra falhas do publicador e permite reconectar.

Google pode manter uploads de projetos não auditados como privados, mesmo com Público
selecionado. OAuth autorizado não remove essa restrição. A fila mostra a visibilidade
real retornada. [Documentação da API](https://developers.google.com/youtube/v3/docs/videos/insert).

Envios interrompidos ficam em `needs_review` ou `uploading` para evitar duplicatas.
Confira o YouTube Studio antes de usar `python -m app.cli.youtube retry CLIP_ID
--confirmed-not-uploaded`. O comando `python -m app.cli.youtube status` mostra a fila.

## Arquivos e Windows

Credenciais importadas ficam em `storage/youtube/client.json`; token e fila existentes
continuam em `storage/youtube-token.json` e `storage/youtube-uploads.db`, preservando
conexões e recibos. As preferências também ficam nesse banco. Todo `storage/` é ignorado
pelo Git. Nunca compartilhe esses arquivos nem `.env`.

Compile com `powershell -File scripts/build-windows.ps1`. O resultado é `SignalCut.exe`
na raiz. Ele precisa do projeto, `.venv` Python 3.12+ com dependências e FFmpeg/FFprobe.
Não é um instalador independente. Feche e reabra o SignalCut depois de atualizar o executável.
