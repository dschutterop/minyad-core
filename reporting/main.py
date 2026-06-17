"""Minyad reporting service scaffold."""

from __future__ import annotations

import time

from shared.db import init_db


def main() -> None:
    init_db()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
