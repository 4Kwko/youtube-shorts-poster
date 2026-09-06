"""Entrypoint do worker local.

python -m app.worker
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory
from app.jobs.queue import InMemoryJobQueue
from app.jobs.worker import Worker

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    settings.ensure_storage_dirs()

    engine = create_db_engine(settings)
    worker = Worker(settings, create_session_factory(engine), InMemoryJobQueue())

    try:
        worker.run_forever()
    except KeyboardInterrupt:
        logger.info("Worker encerrado pelo operador")
        return 0
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
