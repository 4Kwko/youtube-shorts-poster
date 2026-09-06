"""Testes de mapeamento, chunking e geração de ASS."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.schemas.transcript import TranscriptResult, TranscriptSegment, TranscriptWord
from app.services.rendering import build_filtergraph, escape_filter_path, plan_layout
from app.services.subtitles import (
    build_ass,
    build_events,
    escape_ass_text,
    format_timestamp,
    slice_transcript,
    subtitle_file_key,
    wrap_text,
    write_subtitle,
)
from app.services.subtitles.ass import PLAY_RES_X, PLAY_RES_Y


def _words(*items: tuple[float, float, str]) -> list[TranscriptWord]:
    return [TranscriptWord(start=start, end=end, word=word) for start, end, word in items]


GLOBAL_TRANSCRIPT = TranscriptResult(
    language="pt",
    duration=300.0,
    segments=[
        TranscriptSegment(
            start=100.0,
            end=105.0,
            text="Antes do clip.",
            words=_words((100.0, 102.0, "Antes"), (102.0, 105.0, "clip.")),
        ),
        TranscriptSegment(
            start=178.0,
            end=186.0,
            text="Isso começa antes e entra no clip.",
            words=_words(
                (178.0, 179.0, "Isso"),
                (179.0, 179.9, "começa"),
                (184.2, 184.6, "entra"),
                (185.0, 186.0, "clip."),
            ),
        ),
        TranscriptSegment(
            start=200.0,
            end=203.0,
            text="Totalmente dentro.",
            words=_words((200.0, 201.0, "Totalmente"), (201.0, 203.0, "dentro.")),
        ),
        TranscriptSegment(
            start=268.0,
            end=275.0,
            text="Atravessa o fim do clip.",
            words=_words(
                (268.0, 269.0, "Atravessa"),
                (269.0, 269.8, "fim"),
                (271.0, 275.0, "depois."),
            ),
        ),
    ],
)


# --- global → local -------------------------------------------------------


def test_maps_global_timestamps_to_clip_local() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)
    entra = next(
        word for segment in local.segments for word in segment.words if word.word == "entra"
    )

    assert entra.start == 4.2
    assert entra.end == 4.6
    assert local.duration == 90.0


def test_segments_outside_the_clip_are_dropped() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)

    assert all("Antes" not in segment.text for segment in local.segments)
    assert len(local.segments) == 3


def test_segment_crossing_the_start_is_clamped() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)
    crossing = local.segments[0]

    assert crossing.start == 0.0
    # Palavras faladas antes do clip não entram no texto local.
    assert crossing.text == "entra clip."
    assert [word.word for word in crossing.words] == ["entra", "clip."]


def test_segment_crossing_the_end_is_clamped() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)
    crossing = local.segments[-1]

    assert crossing.end == 90.0
    assert crossing.text == "Atravessa fim"
    assert all(word.end <= 90.0 for word in crossing.words)


def test_no_local_timestamp_is_negative_or_beyond_duration() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)

    for segment in local.segments:
        assert 0.0 <= segment.start <= segment.end <= 90.0
        for word in segment.words:
            assert 0.0 <= word.start <= word.end <= 90.0


def test_slicing_preserves_order_and_does_not_mutate_the_global() -> None:
    before = GLOBAL_TRANSCRIPT.model_dump()

    local = slice_transcript(GLOBAL_TRANSCRIPT, 180.0, 270.0)

    assert [segment.start for segment in local.segments] == sorted(
        segment.start for segment in local.segments
    )
    assert GLOBAL_TRANSCRIPT.model_dump() == before


def test_clip_without_speech_yields_no_segments() -> None:
    local = slice_transcript(GLOBAL_TRANSCRIPT, 120.0, 170.0)

    assert local.segments == []


def test_invalid_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="end_time"):
        slice_transcript(GLOBAL_TRANSCRIPT, 100.0, 100.0)


# --- chunking -------------------------------------------------------------


def _phrase() -> TranscriptResult:
    words = [
        (0.0, 0.4, "Hoje"),
        (0.4, 0.6, "eu"),
        (0.6, 1.0, "quero"),
        (1.0, 1.5, "explicar"),
        (1.5, 1.8, "uma"),
        (1.8, 2.2, "coisa"),
        (2.2, 2.6, "muito"),
        (2.6, 3.2, "importante"),
        (3.2, 3.6, "sobre"),
        (3.6, 4.4, "inteligência"),
        (4.4, 5.2, "artificial."),
    ]
    return TranscriptResult(
        duration=6.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=5.2,
                text="Hoje eu quero explicar uma coisa muito importante sobre "
                "inteligência artificial.",
                words=_words(*words),
            )
        ],
    )


def test_events_have_between_two_and_five_words() -> None:
    events = build_events(_phrase())

    assert len(events) >= 3
    assert all(1 <= len(event.words) <= 5 for event in events)
    assert " ".join(event.text for event in events).replace("  ", " ").startswith("Hoje eu quero")


def test_events_preserve_word_order() -> None:
    events = build_events(_phrase())
    words = [word.word for event in events for word in event.words]

    assert words == [word.word for word in _phrase().segments[0].words]


def test_pause_forces_a_break() -> None:
    transcript = TranscriptResult(
        duration=10.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=6.0,
                text="uma duas três quatro",
                words=_words(
                    (0.0, 0.4, "uma"),
                    (0.4, 0.8, "duas"),
                    # Pausa de 1.2s entre "duas" e "três".
                    (2.0, 2.4, "três"),
                    (2.4, 2.8, "quatro"),
                ),
            )
        ],
    )

    events = build_events(transcript)

    assert [event.text for event in events][:2] == ["uma duas", "três quatro"]


def test_sentence_punctuation_forces_a_break() -> None:
    transcript = TranscriptResult(
        duration=10.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=4.0,
                text="Acabou. Recomeça agora",
                words=_words(
                    (0.0, 0.5, "Acabou."),
                    (0.5, 1.0, "Recomeça"),
                    (1.0, 1.5, "agora"),
                ),
            )
        ],
    )

    events = build_events(transcript)

    assert events[0].text == "Acabou."


def test_long_words_break_before_exceeding_line_length() -> None:
    events = build_events(_phrase(), max_chars=20)

    assert all(len(event.text) <= 24 for event in events)


def test_short_events_are_stretched_to_minimum_duration() -> None:
    transcript = TranscriptResult(
        duration=10.0,
        segments=[
            TranscriptSegment(
                start=0.0,
                end=0.2,
                text="Oi.",
                words=_words((0.0, 0.2, "Oi.")),
            )
        ],
    )

    events = build_events(transcript, min_duration=0.6)

    assert events[0].duration >= 0.6
    assert events[0].end <= 10.0


def test_segment_without_word_timestamps_becomes_one_event() -> None:
    transcript = TranscriptResult(
        duration=5.0,
        segments=[TranscriptSegment(start=0.0, end=3.0, text="Sem palavras.", words=[])],
    )

    events = build_events(transcript)

    assert [event.text for event in events] == ["Sem palavras."]


def test_empty_transcript_yields_no_events() -> None:
    assert build_events(TranscriptResult(duration=5.0, segments=[])) == []


# --- ASS ------------------------------------------------------------------


def test_ass_header_matches_vertical_resolution() -> None:
    content = build_ass(build_events(_phrase()))

    assert f"PlayResX: {PLAY_RES_X}" in content
    assert f"PlayResY: {PLAY_RES_Y}" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "Style: bold," in content
    assert content.count("Dialogue:") == len(build_events(_phrase()))


def test_ass_style_keeps_subtitles_away_from_the_bottom_ui() -> None:
    """TikTok/Reels desenham UI no rodapé; a margem vertical evita a colisão."""
    from app.services.subtitles import BOLD_STYLE

    assert BOLD_STYLE.margin_vertical >= 300
    assert BOLD_STYLE.alignment == 2
    assert BOLD_STYLE.bold == -1
    assert BOLD_STYLE.outline >= 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Olá, tudo bem?", "Olá, tudo bem?"),
        ("Não é coincidência", "Não é coincidência"),
        ("d'água", "d'água"),
        ("{\\an8}injetado", "\\{\\\\an8\\}injetado"),
        ("a}b{c", "a\\}b\\{c"),
        ("caminho\\arquivo", "caminho\\\\arquivo"),
        ("linha1\nlinha2", "linha1\\Nlinha2"),
        ("linha1\r\nlinha2", "linha1\\Nlinha2"),
    ],
)
def test_ass_escaping(raw: str, expected: str) -> None:
    assert escape_ass_text(raw) == expected


def test_override_tags_in_transcription_are_never_executed() -> None:
    events = build_events(
        TranscriptResult(
            duration=5.0,
            segments=[
                TranscriptSegment(start=0.0, end=2.0, text="{\\an8}{\\c&HFF0000&}texto", words=[])
            ],
        )
    )

    dialogue = next(line for line in build_ass(events).splitlines() if line.startswith("Dialogue:"))
    text_field = dialogue.split(",", 9)[9]

    # Toda chave está escapada, então o libass renderiza literalmente.
    assert "\\{" in text_field
    assert not any(
        char == "{" and (index == 0 or text_field[index - 1] != "\\")
        for index, char in enumerate(text_field)
    )


def test_ass_preserves_accents() -> None:
    events = build_events(
        TranscriptResult(
            duration=5.0,
            segments=[TranscriptSegment(start=0.0, end=2.0, text="Atenção, coração!", words=[])],
        )
    )

    assert "Atenção, coração!" in build_ass(events)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "0:00:00.00"), (1.5, "0:00:01.50"), (61.25, "0:01:01.25"), (3661.0, "1:01:01.00")],
)
def test_timestamp_format(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_wrap_text_uses_at_most_two_lines() -> None:
    wrapped = wrap_text("uma frase razoavelmente longa para caber numa linha", 20)

    assert wrapped.count("\\N") == 1
    assert "uma frase" in wrapped


def test_short_text_is_not_wrapped() -> None:
    assert wrap_text("curto", 32) == "curto"


# --- storage e filtro -----------------------------------------------------


def test_subtitle_is_written_under_the_video_directory(settings: Settings) -> None:
    settings.ensure_storage_dirs()

    path = write_subtitle(settings, "video123", 2, "conteúdo")

    assert path.name == "002.ass"
    assert path.parent.name == "video123"
    assert path.read_text(encoding="utf-8") == "conteúdo"
    assert subtitle_file_key("video123", 2) == "video123/002.ass"


def test_filter_chain_burns_subtitles_over_the_final_composition() -> None:
    chain = build_filtergraph(plan_layout(1920, 1080), subtitles_path="/s/000.ass")

    # Depois do overlay: a legenda cai sobre a composição 1080x1920 inteira.
    assert chain.index("overlay=") < chain.index("subtitles=")
    assert "subtitles=filename='/s/000.ass'" in chain


def test_filter_chain_without_subtitles_is_unchanged() -> None:
    chain = build_filtergraph(plan_layout(1920, 1080))

    assert "subtitles" not in chain


def test_filter_path_escaping() -> None:
    assert escape_filter_path("/a/b:c") == "/a/b\\:c"
    assert escape_filter_path("/a/it's") == "/a/it\\'s"


# --- tamanho da fonte configurável ---------------------------------------


def test_style_font_size_can_be_overridden() -> None:
    from app.services.subtitles import get_style

    default = get_style()
    bigger = get_style(font_size=96)

    assert default.font_size == 72
    assert bigger.font_size == 96
    # Só o tamanho muda: outline, posição e alinhamento continuam do preset.
    assert (bigger.outline, bigger.margin_vertical, bigger.alignment) == (
        default.outline,
        default.margin_vertical,
        default.alignment,
    )


def test_ass_uses_the_requested_font_size() -> None:
    from app.services.subtitles import get_style

    events = build_events(_phrase())

    assert "Style: bold,DejaVu Sans,110," in build_ass(events, style=get_style(font_size=110))
    assert "Style: bold,DejaVu Sans,72," in build_ass(events)


def test_invalid_font_size_is_rejected() -> None:
    from app.services.subtitles import get_style

    with pytest.raises(ValueError, match="positivo"):
        get_style(font_size=0)


# --- presets, posição e cores ---------------------------------------------


def test_style_presets_differ_in_weight_and_outline() -> None:
    from app.services.subtitles import get_style

    bold = get_style("bold")
    minimal = get_style("minimal")
    outline = get_style("outline")

    assert bold.bold == -1 and minimal.bold == 0
    assert outline.outline > bold.outline > minimal.outline
    assert minimal.shadow == 0.0


def test_unknown_style_is_rejected() -> None:
    from app.services.subtitles import get_style

    with pytest.raises(ValueError, match="desconhecido"):
        get_style("karaoke")


@pytest.mark.parametrize(("position", "margin"), [("top", 1360), ("center", 860), ("bottom", 420)])
def test_position_presets_map_to_margins(position: str, margin: int) -> None:
    from app.models.enums import SubtitlePosition
    from app.services.subtitles.ass import resolve_margin

    assert resolve_margin(SubtitlePosition(position), 0) == margin


def test_offset_takes_precedence_over_the_preset() -> None:
    from app.models.enums import SubtitlePosition
    from app.services.subtitles.ass import resolve_margin

    assert resolve_margin(SubtitlePosition.BOTTOM, 200) == 620
    assert resolve_margin(SubtitlePosition.BOTTOM, -200) == 220


def test_offset_stays_inside_the_frame() -> None:
    from app.models.enums import SubtitlePosition
    from app.services.subtitles.ass import (
        MAX_MARGIN_VERTICAL,
        MIN_MARGIN_VERTICAL,
        resolve_margin,
    )

    assert resolve_margin(SubtitlePosition.TOP, 400) <= MAX_MARGIN_VERTICAL
    assert resolve_margin(SubtitlePosition.BOTTOM, -400) >= MIN_MARGIN_VERTICAL


@pytest.mark.parametrize(
    ("hex_color", "ass_colour"),
    [("#FFFFFF", "&H00FFFFFF"), ("#000000", "&H00000000"), ("#FFCC00", "&H0000CCFF")],
)
def test_hex_colours_become_ass_bgr(hex_color: str, ass_colour: str) -> None:
    from app.services.subtitles.ass import hex_to_ass_colour

    assert hex_to_ass_colour(hex_color) == ass_colour


def test_colours_reach_the_style_line() -> None:
    from app.services.subtitles import get_style

    content = build_ass(
        build_events(_phrase()),
        style=get_style("bold", text_color="#FFCC00", outline_color="#101010"),
    )

    assert "&H0000CCFF" in content
    assert "&H00101010" in content
