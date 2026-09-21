"""Configuration is read from real process environment; no implicit .env loading."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() not in ('1', '0', 'true', 'false', 'yes', 'no'):
        raise ValueError('Invalid boolean configuration: ' + name)
    return value.lower() in ('1', 'true', 'yes')


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path.home() / '.local/share/hoshino/maimai_updata')
    encryption_key: str = field(default='', repr=False)
    auto_images: bool = True
    allow_bare_codes: bool = True
    upload_command: str = '上传成绩'
    max_images: int = 3
    max_concurrent: int = 2
    cooldown: float = 5.0
    duplicate_ttl: float = 120.0
    upload_timeout: float = 120.0
    image_timeout: float = 10.0
    max_image_bytes: int = 8 * 1024 * 1024
    max_pixels: int = 12_000_000
    local_image_roots: tuple = ()
    arcade_proxy: str = field(default=None, repr=False)

    @classmethod
    def from_env(cls):
        cfg = cls(
            data_dir=Path(os.getenv('MAIMAI_UPLOAD_DATA_DIR', str(cls().data_dir))).expanduser(),
            encryption_key=os.getenv('MAIMAI_UPLOAD_KEY', ''),
            auto_images=_bool('MAIMAI_UPLOAD_AUTO_IMAGES', True),
            allow_bare_codes=_bool('MAIMAI_UPLOAD_BARE_CODES', True),
            upload_command=os.getenv('MAIMAI_UPLOAD_COMMAND', '上传成绩').strip(),
            max_images=int(os.getenv('MAIMAI_UPLOAD_MAX_IMAGES', '3')),
            max_concurrent=int(os.getenv('MAIMAI_UPLOAD_CONCURRENCY', '2')),
            cooldown=float(os.getenv('MAIMAI_UPLOAD_COOLDOWN', '5')),
            duplicate_ttl=float(os.getenv('MAIMAI_UPLOAD_DEDUP_TTL', '120')),
            upload_timeout=float(os.getenv('MAIMAI_UPLOAD_TIMEOUT', '120')),
            image_timeout=float(os.getenv('MAIMAI_UPLOAD_IMAGE_TIMEOUT', '10')),
            max_image_bytes=int(os.getenv('MAIMAI_UPLOAD_MAX_IMAGE_BYTES', str(8*1024*1024))),
            max_pixels=int(os.getenv('MAIMAI_UPLOAD_MAX_PIXELS', '12000000')),
            local_image_roots=tuple(Path(p).expanduser() for p in os.getenv('MAIMAI_UPLOAD_LOCAL_IMAGE_ROOTS', '').split(os.pathsep) if p),
            arcade_proxy=os.getenv('MAIMAI_UPLOAD_ARCADE_PROXY') or None,
        )
        if not cfg.upload_command or len(cfg.upload_command) > 32:
            raise ValueError('Invalid upload command configuration')
        if not 1 <= cfg.max_images <= 5 or not 1 <= cfg.max_concurrent <= 8:
            raise ValueError('Invalid concurrency/image configuration')
        if not (1 <= cfg.cooldown <= 3600 and 10 <= cfg.duplicate_ttl <= 3600 and 5 <= cfg.upload_timeout <= 300 and 1 <= cfg.image_timeout <= 30):
            raise ValueError('Invalid timeout configuration')
        if not (1024 <= cfg.max_image_bytes <= 16*1024*1024 and 1000 <= cfg.max_pixels <= 20_000_000):
            raise ValueError('Invalid image limits')
        return cfg
