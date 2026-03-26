"""
Günlük (logging) altyapısı — Türkçe log çıktısı için merkezi yapılandırma.
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Tüm uygulama için merkezi log yapılandırması."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Üçüncü taraf kütüphanelerin gürültüsünü azalt
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
