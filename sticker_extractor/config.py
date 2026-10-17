from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

STICKER_SIZE = 512
TRAY_SIZE = 96

STATIC_MAX_BYTES = 100 * 1024
ANIMATED_MAX_BYTES = 500 * 1024
TRAY_MAX_BYTES = 50 * 1024
PACK_MAX_STICKERS = 30

MAX_ANIM_SECONDS = 6.0
ANIM_FPS = 15

TIKTOK_HOME = "https://www.tiktok.com/"
TIKTOK_LOGIN = "https://www.tiktok.com/login"
TIKTOK_MESSAGES = "https://www.tiktok.com/messages"

SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")


@dataclass
class Config:
    profile_dir: Path = BASE_DIR / ".browser_profile"
    raw_dir: Path = BASE_DIR / "stickers_raw"
    ready_dir: Path = BASE_DIR / "stickers_ready"
    pack_dir: Path = BASE_DIR / "pack"
    zip_path: Path = BASE_DIR / "stickers-pack.zip"

    static_max_bytes: int = STATIC_MAX_BYTES
    animated_max_bytes: int = ANIMATED_MAX_BYTES
    max_anim_seconds: float = MAX_ANIM_SECONDS
    fps: int = ANIM_FPS
    size: int = STICKER_SIZE

    headless: bool = False
    debug: bool = False
    scroll_rounds: int = 15
    scroll_delay: float = 0.8
    port: int = 8000
    serve: bool = True
    pack_name: str = "Stickers de TikTok"
    pack_author: str = "TikTok"

    def ensure_dirs(self) -> None:
        for path in (self.profile_dir, self.raw_dir, self.ready_dir, self.pack_dir):
            path.mkdir(parents=True, exist_ok=True)
