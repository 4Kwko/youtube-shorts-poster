"""Fila de jobs.

O banco é a fonte de verdade do estado; a fila carrega apenas identificadores.
Perder a fila nunca perde trabalho — o worker reconstrói a partir da tabela
`jobs` na inicialização.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Protocol


class JobQueue(Protocol):
    """Contrato mínimo. Uma implementação Redis entra aqui sem tocar nos services."""

    def enqueue(self, job_id: str) -> None:
        """Coloca o job na fila. Reenfileirar um job já pendente é no-op."""
        ...

    def get_next(self) -> str | None:
        """Próximo job pendente, ou `None` se a fila estiver vazia."""
        ...

    def acknowledge(self, job_id: str) -> None:
        """Confirma o processamento e libera o job para novo enfileiramento."""
        ...

    def fail(self, job_id: str, *, requeue: bool) -> None:
        """Encerra o processamento com falha, opcionalmente devolvendo à fila."""
        ...

    def __len__(self) -> int: ...


class InMemoryJobQueue:
    """Fila em processo, para desenvolvimento local.

    LIMITAÇÃO CONHECIDA: vive na memória de um processo. Não atravessa
    processos e não sobrevive a restart — por isso o worker varre o banco ao
    iniciar e em cada ciclo ocioso. Substituir por Redis é trocar esta classe.
    """

    def __init__(self) -> None:
        self._pending: deque[str] = deque()
        self._known: set[str] = set()
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            # Evita processar o mesmo job duas vezes no mesmo processo.
            if job_id in self._known or job_id in self._in_flight:
                return
            self._pending.append(job_id)
            self._known.add(job_id)

    def get_next(self) -> str | None:
        with self._lock:
            if not self._pending:
                return None
            job_id = self._pending.popleft()
            self._known.discard(job_id)
            self._in_flight.add(job_id)
            return job_id

    def acknowledge(self, job_id: str) -> None:
        with self._lock:
            self._in_flight.discard(job_id)

    def fail(self, job_id: str, *, requeue: bool) -> None:
        with self._lock:
            self._in_flight.discard(job_id)
            if requeue and job_id not in self._known:
                self._pending.append(job_id)
                self._known.add(job_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)
