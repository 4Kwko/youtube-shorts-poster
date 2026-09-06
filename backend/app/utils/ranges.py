"""Parser do header `Range`.

Função pura sobre a string do header e o tamanho do arquivo, para que o
comportamento de borda seja testável sem HTTP nem disco.

Segue a RFC 9110: header sintaticamente inválido é ignorado (a resposta vira
200 com o corpo inteiro), enquanto um range válido mas impossível de satisfazer
vira 416.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Aceita apenas `bytes=` com um único intervalo. Multipart/multirange existe na
# RFC mas nenhum player relevante usa para vídeo progressivo.
_RANGE_PATTERN = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")


class RangeNotSatisfiableError(Exception):
    """Range sintaticamente válido, mas fora do arquivo."""


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int  # inclusivo, como no header

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def content_range(self, file_size: int) -> str:
        return f"bytes {self.start}-{self.end}/{file_size}"


def parse_range_header(header: str | None, file_size: int) -> ByteRange | None:
    """Interpreta o header e resolve o intervalo contra o tamanho do arquivo.

    Retorna `None` quando não há range aplicável (ausente ou malformado).
    Levanta `RangeNotSatisfiableError` quando o intervalo não existe no arquivo.
    """
    if header is None or file_size <= 0:
        return None

    match = _RANGE_PATTERN.match(header.strip())
    if match is None:
        return None

    raw_start, raw_end = match.group("start"), match.group("end")

    if not raw_start and not raw_end:
        return None

    if not raw_start:
        # Sufixo: `bytes=-500` são os últimos 500 bytes.
        suffix = int(raw_end)
        if suffix == 0:
            raise RangeNotSatisfiableError
        start = max(file_size - suffix, 0)
        return ByteRange(start=start, end=file_size - 1)

    start = int(raw_start)
    if start >= file_size:
        raise RangeNotSatisfiableError

    # Fim ausente ou além do EOF: entrega até o último byte.
    end = min(int(raw_end), file_size - 1) if raw_end else file_size - 1
    if end < start:
        raise RangeNotSatisfiableError

    return ByteRange(start=start, end=end)
