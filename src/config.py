"""
Yapılandırma yükleyici — config.yaml ve .env dosyalarını okur.
Tüm modüller bu modül üzerinden ayarlara erişir.
"""

import os
import logging
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_config: dict[str, Any] = {}


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """config.yaml'ı yükler ve .env değişkenlerini ortam değişkenlerine ekler."""
    global _config

    # .env dosyasını yükle (varsa)
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug(".env dosyası yüklendi.")
    else:
        load_dotenv(Path(".env.example"))
        logger.debug(".env bulunamadı, .env.example kullanılıyor.")

    # config.yaml'ı yükle
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Yapılandırma dosyası bulunamadı: {config_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)

    # Ortam değişkenlerinden API anahtarlarını üzerine yaz (güvenlik)
    _override_from_env()

    logger.info("Yapılandırma başarıyla yüklendi: %s", config_path)
    return _config


def _override_from_env() -> None:
    """Ortam değişkenlerinden kritik ayarları üzerine yazar."""
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    if telegram_token:
        _config["telegram_token"] = telegram_token


def get(key: str, default: Any = None) -> Any:
    """Nokta notasyonuyla iç içe anahtar erişimi destekler (ör. 'telegram_threads.strong')."""
    if not _config:
        raise RuntimeError("Yapılandırma henüz yüklenmedi. Önce load_config() çağırın.")

    keys = key.split(".")
    value = _config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k, default)
        else:
            return default
    return value


def is_dry_run() -> bool:
    """dry_run modunda mı çalışıyoruz?"""
    return bool(get("dry_run", False))


def all_config() -> dict[str, Any]:
    """Tüm yapılandırma sözlüğünü döndürür."""
    return dict(_config)
