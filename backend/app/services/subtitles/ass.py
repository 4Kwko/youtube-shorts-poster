"""Geração do arquivo `.ass`.

Isolado do FFmpeg e do storage: recebe eventos, devolve texto. O escaping é a
parte crítica — texto transcrito nunca pode virar override tag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.constants import SUBTITLE_OFFSET_LIMIT
from app.models.enums import SubtitlePosition, SubtitleStylePreset
from app.services.subtitles.chunking import SubtitleEvent

PLAY_RES_X = 1080
PLAY_RES_Y = 1920

# Fonte sem-serifa presente em praticamente qualquer Linux; libass cai para
# outra sem-serifa se faltar.
DEFAULT_FONT = "DejaVu Sans"


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """Preset visual. Por ora existe apenas `bold`."""

    name: str
    font: str = DEFAULT_FONT
    font_size: int = 72
    primary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00000000"
    back_colour: str = "&H80000000"
    bold: int = -1
    outline: float = 5.0
    shadow: float = 2.0
    # Alinhamento 2 = inferior centralizado. A margem alta tira a legenda da
    # faixa onde TikTok/Reels desenham botões e legenda do post.
    alignment: int = 2
    margin_horizontal: int = 90
    margin_vertical: int = 420
    max_chars_per_line: int = 32


BOLD_STYLE = SubtitleStyle(name="bold")

# Presets visuais. Mudam peso, contorno e sombra — não mexem em timing,
# chunking nem escaping.
MINIMAL_STYLE = SubtitleStyle(name="minimal", bold=0, outline=2.0, shadow=0.0, font_size=64)
OUTLINE_STYLE = SubtitleStyle(name="outline", bold=-1, outline=8.0, shadow=0.0, font_size=76)

STYLES: dict[str, SubtitleStyle] = {
    SubtitleStylePreset.BOLD.value: BOLD_STYLE,
    SubtitleStylePreset.MINIMAL.value: MINIMAL_STYLE,
    SubtitleStylePreset.OUTLINE.value: OUTLINE_STYLE,
}

# Distância da base do canvas, em pixels, para cada preset de posição.
# `BOTTOM` é a margem que a legenda já usava antes desta configuração existir.
POSITION_MARGINS: dict[SubtitlePosition, int] = {
    SubtitlePosition.TOP: 1360,
    SubtitlePosition.CENTER: 860,
    SubtitlePosition.BOTTOM: 420,
}

# Limites de segurança: fora disso a legenda encostaria na borda ou sairia do
# frame depois do ajuste fino.
MIN_MARGIN_VERTICAL = 120
MAX_MARGIN_VERTICAL = PLAY_RES_Y - 400


def hex_to_ass_colour(value: str) -> str:
    """Converte `#RRGGBB` para o `&HAABBGGRR` do ASS (BGR, alfa opaco)."""
    cleaned = value.lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("Cor deve estar no formato #RRGGBB.")
    red, green, blue = cleaned[0:2], cleaned[2:4], cleaned[4:6]
    return f"&H00{blue}{green}{red}".upper()


def resolve_margin(position: SubtitlePosition, offset: int) -> int:
    """Margem final da legenda: preset mais o ajuste fino, dentro dos limites.

    O offset tem precedência sobre o preset por construção: ele é somado
    depois, e o resultado é preso à faixa segura.
    """
    bounded_offset = min(max(offset, -SUBTITLE_OFFSET_LIMIT), SUBTITLE_OFFSET_LIMIT)
    margin = POSITION_MARGINS[position] + bounded_offset
    return min(max(margin, MIN_MARGIN_VERTICAL), MAX_MARGIN_VERTICAL)


def get_style(
    name: str = "bold",
    *,
    font_size: int | None = None,
    position: SubtitlePosition | None = None,
    vertical_offset: int = 0,
    text_color: str | None = None,
    outline_color: str | None = None,
) -> SubtitleStyle:
    """Preset de legenda com os ajustes escolhidos para o vídeo.

    O que o preset define (peso, contorno, sombra) só é sobrescrito pelo que o
    usuário mexeu de fato.
    """
    style = STYLES.get(name)
    if style is None:
        raise ValueError(f"Preset de legenda desconhecido: {name!r}")

    if font_size is not None and font_size <= 0:
        raise ValueError("Tamanho de fonte deve ser positivo.")

    margin = style.margin_vertical
    if position is not None or vertical_offset:
        margin = resolve_margin(position or SubtitlePosition.BOTTOM, vertical_offset)

    return replace(
        style,
        font_size=font_size if font_size is not None else style.font_size,
        margin_vertical=margin,
        primary_colour=(
            hex_to_ass_colour(text_color) if text_color is not None else style.primary_colour
        ),
        outline_colour=(
            hex_to_ass_colour(outline_color) if outline_color is not None else style.outline_colour
        ),
    )


def escape_ass_text(text: str) -> str:
    """Neutraliza tudo que o libass interpretaria como comando.

    `{` abriria um bloco de override (`{\\an8}` etc.), e a barra invertida é o
    prefixo dos comandos dentro dele. Quebras de linha viram `\\N`, que é a
    forma correta de quebrar linha em ASS.
    """
    escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\n", "\\N")
    # Vírgula é separador de campo apenas até o campo Text, que é o último da
    # linha Dialogue — por isso não precisa de tratamento.
    return escaped.strip()


def wrap_text(text: str, max_chars: int) -> str:
    """Quebra em no máximo duas linhas, sem cortar palavra."""
    if len(text) <= max_chars or " " not in text:
        return text

    words = text.split()
    middle = len(text) / 2
    best_index = 1
    best_distance = float("inf")

    length = 0
    for index, word in enumerate(words[:-1]):
        length += len(word) + 1
        distance = abs(length - middle)
        if distance < best_distance:
            best_distance = distance
            best_index = index + 1

    return " ".join(words[:best_index]) + "\\N" + " ".join(words[best_index:])


def format_timestamp(seconds: float) -> str:
    """`H:MM:SS.cc`, o formato de tempo do ASS (centésimos, não milésimos)."""
    clamped = max(seconds, 0.0)
    centiseconds = round(clamped * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _style_line(style: SubtitleStyle) -> str:
    return (
        f"Style: {style.name},{style.font},{style.font_size},"
        f"{style.primary_colour},{style.primary_colour},"
        f"{style.outline_colour},{style.back_colour},"
        f"{style.bold},0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},{style.alignment},"
        f"{style.margin_horizontal},{style.margin_horizontal},{style.margin_vertical},1"
    )


def build_ass(events: list[SubtitleEvent], *, style: SubtitleStyle | None = None) -> str:
    """Documento ASS completo para um clip."""
    resolved = style or BOLD_STYLE

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {PLAY_RES_X}",
        f"PlayResY: {PLAY_RES_Y}",
        # Sem isto, outline e sombra não acompanham a escala da resolução.
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 0",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        (
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding"
        ),
        _style_line(resolved),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]

    for event in events:
        if event.end <= event.start:
            continue
        text = wrap_text(escape_ass_text(event.text), resolved.max_chars_per_line)
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{format_timestamp(event.start)},{format_timestamp(event.end)},"
            f"{resolved.name},,0,0,0,,{text}"
        )

    return "\n".join(lines) + "\n"
