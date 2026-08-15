"""Run the Python Component relation-detection Worker."""

from __future__ import annotations

import logging
import signal
import threading

from src.component_repo.go_relation_worker import build_worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    build_worker().run_forever(stop)


if __name__ == "__main__":
    main()
