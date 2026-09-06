"""Enquadramento vertical: decisão de layout e construção do filtergraph.

Tudo aqui é função pura sobre números e strings, então dá para testar a cadeia
de filtros inteira sem invocar o FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import (
    BACKGROUND_MAX_BRIGHTNESS_DROP,
    BLUR_STRENGTH_MAX_SIGMA,
    BLUR_STRENGTH_MIN_SIGMA,
    FOREGROUND_SCALE_DEFAULT,
)
from app.models.enums import OutputFps, RenderQuality, VerticalLayout

# Reexportado: o enum é de domínio (fica em models/enums), mas quem trabalha
# com filtros importa daqui.
__all__ = [
    "DEFAULT_LAYOUT",
    "LayoutPlan",
    "VerticalLayout",
    "blur_resolution",
    "build_background_filter",
    "build_center_crop_filter",
    "build_filtergraph",
    "encoding_args_for",
    "escape_filter_path",
    "plan_layout",
]

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

FOUR_THIRDS = 4 / 3

# O fundo é desfocado numa resolução reduzida e só depois ampliado: o gblur
# custa proporcional à área. A própria redução já borra, então a resolução
# intermediária acompanha a intensidade — sem isso o slider quase não muda o
# resultado, porque a ampliação domina o efeito.
BLUR_MAX_WIDTH = 540
BLUR_MIN_WIDTH = 216


def blur_sigma(strength: int) -> float:
    """Converte a intensidade 0 a 100 em sigma do `gblur`."""
    ratio = min(max(strength, 0), 100) / 100
    span = BLUR_STRENGTH_MAX_SIGMA - BLUR_STRENGTH_MIN_SIGMA
    return round(BLUR_STRENGTH_MIN_SIGMA + span * ratio, 2)


def blur_resolution(strength: int) -> tuple[int, int]:
    """Resolução intermediária do fundo, em 9:16, conforme a intensidade."""
    ratio = min(max(strength, 0), 100) / 100
    width = _even(BLUR_MAX_WIDTH - (BLUR_MAX_WIDTH - BLUR_MIN_WIDTH) * ratio)
    return width, _even(width * 16 / 9)


def background_brightness(darkness: int) -> float:
    """Converte o escurecimento 0 a 100 no ajuste de `eq=brightness`."""
    ratio = min(max(darkness, 0), 100) / 100
    return round(-BACKGROUND_MAX_BRIGHTNESS_DROP * ratio, 3)


DEFAULT_LAYOUT = VerticalLayout.BLURRED_4_3


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    """Geometria resolvida para um vídeo de origem específico."""

    layout: VerticalLayout
    target_width: int
    target_height: int
    # `None` quando o foreground preenche o canvas inteiro (sem fundo).
    foreground_width: int | None = None
    foreground_height: int | None = None
    # Crop central aplicado ao foreground, em pixels da origem.
    crop_width: int | None = None
    crop_height: int | None = None

    @property
    def uses_background(self) -> bool:
        return self.foreground_width is not None and self.foreground_height is not None


def _even(value: float) -> int:
    """Arredonda para par: yuv420p não aceita dimensão ímpar."""
    rounded = round(value)
    return rounded if rounded % 2 == 0 else rounded + 1


def plan_layout(
    source_width: int,
    source_height: int,
    layout: VerticalLayout = DEFAULT_LAYOUT,
    *,
    foreground_scale: int = FOREGROUND_SCALE_DEFAULT,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
) -> LayoutPlan:
    """Decide o enquadramento a partir da proporção da origem.

    `blurred_4_3` corta as laterais até 4:3 quando a origem é mais larga que
    isso; `blurred_16_9` nunca corta, preservando o quadro inteiro. Nos dois, um
    vídeo vertical preenche o canvas como no `center_crop` — forçar uma
    proporção horizontal ali cortaria justamente o que o vídeo tem de útil.

    Nunca há stretch: a proporção do foreground é sempre a do recorte.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Dimensões da origem devem ser positivas.")
    if target_width <= 0 or target_height <= 0:
        raise ValueError("Dimensões de saída devem ser positivas.")

    if layout is VerticalLayout.CENTER_CROP:
        return LayoutPlan(layout=layout, target_width=target_width, target_height=target_height)

    aspect = source_width / source_height

    if aspect < 1.0:
        # Vertical: preenche o canvas, sem fundo desfocado.
        return LayoutPlan(
            layout=VerticalLayout.CENTER_CROP,
            target_width=target_width,
            target_height=target_height,
        )

    if layout is VerticalLayout.BLURRED_4_3 and aspect > FOUR_THIRDS:
        crop_width = _even(source_height * FOUR_THIRDS)
        crop_height = _even(source_height)
        foreground_aspect = FOUR_THIRDS
    else:
        # `blurred_16_9` preserva o frame inteiro: só reduz até a largura do
        # canvas e deixa o fundo desfocado cobrir o resto.
        crop_width = _even(source_width)
        crop_height = _even(source_height)
        foreground_aspect = aspect

    # Escala do vídeo central. Reduz a partir da largura do canvas, e nunca
    # deixa a altura passar do canvas — o foreground sempre cabe inteiro.
    scale = min(max(foreground_scale, 1), 100) / 100
    foreground_width = _even(target_width * scale)
    foreground_height = _even(foreground_width / foreground_aspect)

    if foreground_height > target_height:
        foreground_height = _even(target_height)
        foreground_width = _even(foreground_height * foreground_aspect)

    return LayoutPlan(
        layout=layout,
        target_width=target_width,
        target_height=target_height,
        foreground_width=foreground_width,
        foreground_height=foreground_height,
        crop_width=min(crop_width, source_width),
        crop_height=min(crop_height, source_height),
    )


def build_center_crop_filter(width: int, height: int) -> str:
    """Preenche `width`x`height` cortando o excedente, sem deformar.

    `force_original_aspect_ratio=increase` escala pelo lado que falta, então a
    imagem sempre cobre o quadro inteiro — nunca sobra barra preta. O `crop`
    seguinte é centralizado por padrão. `setsar=1` evita que um SAR não
    quadrado da origem faça o player esticar o resultado.
    """
    if width <= 0 or height <= 0:
        raise ValueError("Dimensões de saída devem ser positivas.")

    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "setsar=1"
    )


def build_background_filter(width: int, height: int, *, strength: int, brightness: float) -> str:
    """Fundo: o próprio vídeo ampliado até cobrir o canvas e desfocado."""
    blur_width, blur_height = blur_resolution(strength)
    return (
        f"scale={blur_width}:{blur_height}:force_original_aspect_ratio=increase,"
        f"crop={blur_width}:{blur_height},"
        f"gblur=sigma={blur_sigma(strength)},"
        f"eq=brightness={brightness},"
        f"scale={width}:{height},"
        "setsar=1"
    )


def escape_filter_path(path: str) -> str:
    r"""Escapa um caminho para uso dentro de um argumento de filtro do FFmpeg.

    O filtergraph usa `:` para separar opções e `\` como escape, então um
    caminho cru quebraria o parser (ou pior, seria interpretado). Isto não tem
    relação com shell — os argumentos continuam indo em lista.
    """
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _subtitles_filter(subtitles_path: str) -> str:
    return f"subtitles=filename='{escape_filter_path(subtitles_path)}'"


def build_filtergraph(
    plan: LayoutPlan,
    *,
    subtitles_path: str | None = None,
    blur_strength: int = 40,
    background_darkness: int = 34,
    fps: OutputFps = OutputFps.ORIGINAL,
) -> str:
    """Filtergraph completo, com saída rotulada `[v]`.

    Enquadramento, composição e burn-in da legenda ficam no mesmo grafo: cada
    clip sai em uma única execução do FFmpeg, sem arquivo intermediário.
    """
    subtitles = f",{_subtitles_filter(subtitles_path)}" if subtitles_path else ""
    # Antes da legenda: reamostrar depois faria o libass desenhar em frames que
    # seriam descartados.
    rate = "" if fps is OutputFps.ORIGINAL else f",fps={fps.value}"

    if not plan.uses_background:
        chain = build_center_crop_filter(plan.target_width, plan.target_height)
        return f"[0:v]{chain}{rate}{subtitles}[v]"

    if plan.crop_width is None or plan.crop_height is None:
        raise ValueError("Plano com fundo exige crop definido.")

    background = build_background_filter(
        plan.target_width,
        plan.target_height,
        strength=blur_strength,
        brightness=background_brightness(background_darkness),
    )
    foreground = (
        f"crop={plan.crop_width}:{plan.crop_height},"
        f"scale={plan.foreground_width}:{plan.foreground_height},"
        "setsar=1"
    )

    return (
        # `split` duplica a origem: fundo e foreground vêm do mesmo frame.
        "[0:v]split=2[bg][fg];"
        f"[bg]{background}[bgout];"
        f"[fg]{foreground}[fgout];"
        # A legenda é desenhada depois do overlay, sobre a composição final.
        f"[bgout][fgout]overlay=(W-w)/2:(H-h)/2{rate}{subtitles},setsar=1[v]"
    )


# Preset e CRF por perfil de qualidade. `BALANCED` reproduz o encoding que
# existia antes desta opção.
QUALITY_PRESETS: dict[RenderQuality, tuple[str, str]] = {
    RenderQuality.FAST: ("superfast", "24"),
    RenderQuality.BALANCED: ("veryfast", "21"),
    RenderQuality.HIGH: ("slow", "18"),
}


def encoding_args_for(quality: RenderQuality) -> tuple[str, ...]:
    preset, crf = QUALITY_PRESETS[quality]
    return (
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        crf,
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
    )


VIDEO_ENCODING_ARGS: tuple[str, ...] = encoding_args_for(RenderQuality.BALANCED)


def build_audio_filter(volume: int, normalize: bool) -> str | None:
    """Filtro de áudio, ou `None` quando nada precisa ser aplicado.

    A normalização vem antes do ganho manual: inverter a ordem faria o
    `loudnorm` desfazer o volume escolhido.
    """
    steps: list[str] = []
    if normalize:
        steps.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if volume != 100:
        steps.append(f"volume={max(volume, 0) / 100:.2f}")
    return ",".join(steps) if steps else None


AUDIO_ENCODING_ARGS: tuple[str, ...] = (
    "-c:a",
    "aac",
    "-b:a",
    "128k",
    "-ar",
    "44100",
)

CONTAINER_ARGS: tuple[str, ...] = ("-movflags", "+faststart")
