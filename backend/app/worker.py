"""Entrypoint do worker local.

python -m app.worker
"""

from __future__ import annotations

import logging
import threading

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

    stop_uploads = threading.Event()

    def publish_pending() -> None:
        from app.services.youtube import drain, publishing_error
        from app.services.youtube_preferences import preferences

        while not stop_uploads.is_set():
            try:
                if preferences(settings).enabled:
                    drain(settings, respect_pause=True)
                    publishing_error(settings, save=True)
            except Exception:
                publishing_error(
                    settings,
                    "Envio pausado por falha de conexão, autorização ou "
                    "API. Confira o canal e reconecte se necessário.",
                    save=True,
                )
                logger.warning("YouTube upload paused; use app.cli.youtube status to inspect.")
            stop_uploads.wait(30)

    threading.Thread(target=publish_pending, daemon=True, name="youtube-publisher").start()

    try:
        worker.run_forever()
    except KeyboardInterrupt:
        logger.info("Worker encerrado pelo operador")
        return 0
    finally:
        stop_uploads.set()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
