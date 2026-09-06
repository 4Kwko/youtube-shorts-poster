"""Constantes de domínio compartilhadas entre API, banco e pipeline."""

from __future__ import annotations

# Durações oferecidas na interface. Lista fechada: qualquer outro valor é
# recusado com 422, e é esta lista que o frontend espelha.
CLIP_DURATION_OPTIONS: tuple[int, ...] = (
    30,
    60,
    90,
    120,
    150,
    180,
)

DEFAULT_CLIP_DURATION_SECONDS = 90

# Quantos vídeos um único envio pode criar. Limite existe nos dois lados: a UI
# impede passar disso, e a API recusa de qualquer forma.
MAX_BATCH_VIDEOS = 20

SUBTITLE_FONT_SIZE_MIN = 48
SUBTITLE_FONT_SIZE_MAX = 110
DEFAULT_SUBTITLE_FONT_SIZE = 72

# Ajuste fino da legenda, em pixels na grade 1080x1920.
SUBTITLE_OFFSET_LIMIT = 400

# Blur e escurecimento entram como 0 a 100 na API e viram parâmetro de filtro no
# renderer. Os defaults reproduzem o resultado anterior a estas opções.
BLUR_STRENGTH_MIN_SIGMA = 4.0
BLUR_STRENGTH_MAX_SIGMA = 26.0
BLUR_STRENGTH_DEFAULT = 40

BACKGROUND_MAX_BRIGHTNESS_DROP = 0.35
BACKGROUND_DARKNESS_DEFAULT = 34

# Percentual da largura do canvas ocupada pelo vídeo central.
FOREGROUND_SCALE_MIN = 60
FOREGROUND_SCALE_MAX = 100
FOREGROUND_SCALE_DEFAULT = 100

VOLUME_DEFAULT = 100
