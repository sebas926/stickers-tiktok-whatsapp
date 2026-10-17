from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .config import TRAY_MAX_BYTES, TRAY_SIZE, Config

ANIMATED_SUFFIXES = (".webm", ".mp4", ".mov")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".awebp", ".gif")
STATIC_QUALITIES = (90, 80, 70, 60, 50, 40, 30, 25, 20, 15, 10)
ANIMATED_QUALITIES = (75, 65, 55, 45, 35, 25, 18, 14, 10)
ANIMATED_FPS_FALLBACK = (12, 10, 8, 6)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_all(config: Config) -> list[Path]:
    config.ensure_dirs()
    results: list[Path] = []
    sources = sorted(
        p
        for p in config.raw_dir.iterdir()
        if p.is_file() and p.suffix not in (".part", ".json")
    )
    if not sources:
        print(f"No hay archivos en {config.raw_dir}")
        return results

    if not ffmpeg_available():
        print("AVISO: no encontré 'ffmpeg' en el sistema.")
        print("Los stickers animados no se podrán convertir (los fijos sí).")
        print("Instálalo desde https://ffmpeg.org/download.html y agrégalo al PATH.")

    for index, source in enumerate(sources, start=1):
        destination = config.ready_dir / f"{source.stem}.webp"
        try:
            if _is_animated(source):
                if not ffmpeg_available():
                    print(f"  [{index}/{len(sources)}] omitido animado (sin ffmpeg): {source.name}")
                    continue
                ok = convert_animated(source, destination, config)
            else:
                ok = convert_static(source, destination, config)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            print(f"  [{index}/{len(sources)}] error con {source.name}: {exc}")
            continue
        if ok:
            results.append(destination)
            print(
                f"  [{index}/{len(sources)}] {source.name} -> {destination.name} "
                f"({destination.stat().st_size} bytes)"
            )
        else:
            destination.unlink(missing_ok=True)
            print(f"  [{index}/{len(sources)}] no se pudo convertir {source.name}")
    return results


def convert_static(source: Path, destination: Path, config: Config) -> bool:
    image = _load_image(source)
    if image is None:
        return False
    square = _fit_square(image, config.size)
    for quality in STATIC_QUALITIES:
        square.save(destination, "WEBP", quality=quality, method=6)
        if destination.stat().st_size <= config.static_max_bytes:
            return True
    return destination.stat().st_size <= config.static_max_bytes


def convert_animated(source: Path, destination: Path, config: Config) -> bool:
    extracted = None
    input_fps = None
    if _sniff_kind(source) == "image" and _image_is_animated(source):
        target_dir = Path(
            tempfile.mkdtemp(prefix="sticker_frames_", dir=str(config.raw_dir))
        )
        input_fps = _extract_webp_frames(source, target_dir, config)
        if input_fps is None:
            return destination.exists() and destination.stat().st_size > 0
        extracted = target_dir
    try:
        durations = []
        for candidate in (
            config.max_anim_seconds,
            min(4.0, config.max_anim_seconds),
            min(3.0, config.max_anim_seconds),
            min(2.0, config.max_anim_seconds),
        ):
            if candidate not in durations and candidate > 0:
                durations.append(candidate)
        for seconds in durations:
            for fps in (input_fps or config.fps, *ANIMATED_FPS_FALLBACK):
                for quality in ANIMATED_QUALITIES:
                    if _run_webp_ffmpeg(
                        extracted or source, destination, config, fps, quality, seconds
                    ):
                        if destination.stat().st_size <= config.animated_max_bytes:
                            return True
    finally:
        if extracted is not None:
            import shutil

            shutil.rmtree(extracted, ignore_errors=True)
    if destination.exists():
        destination.unlink()
    return False


def _image_is_animated(source: Path) -> bool:
    try:
        with Image.open(source) as image:
            return bool(getattr(image, "is_animated", False))
    except Exception:
        return False


def _extract_webp_frames(
    source: Path, target_dir: Path, config: Config
) -> int | None:
    try:
        with Image.open(source) as image:
            frame_count = getattr(image, "n_frames", 1)
            durations = []
            for i in range(frame_count):
                image.seek(i)
                durations.append(max(1, image.info.get("duration", 100)) / 1000.0)
            timeline = []
            elapsed = 0.0
            for i, duration in enumerate(durations):
                timeline.append((elapsed, i))
                elapsed += duration
            limit = min(elapsed, config.max_anim_seconds)
            fps = max(1, min(config.fps, frame_count))
            ticks = max(1, int(limit * fps))
            chosen: list[int] = []
            cursor = 0
            for t in range(ticks):
                stamp = t / fps
                while cursor + 1 < len(timeline) and timeline[cursor + 1][0] <= stamp:
                    cursor += 1
                chosen.append(timeline[cursor][1])
            for j, frame_index in enumerate(chosen):
                image.seek(frame_index)
                image.convert("RGBA").save(target_dir / f"seq_{j:04d}.png")
        return fps
    except Exception:
        return None


def make_tray(source: Path, destination: Path, config: Config) -> bool:
    image = _load_image(source)
    if image is None:
        return False
    square = _fit_square(image, TRAY_SIZE)
    for quality in STATIC_QUALITIES:
        square.save(destination, "PNG", optimize=True)
        if destination.stat().st_size <= TRAY_MAX_BYTES:
            return True
    return destination.exists()


def _is_animated(source: Path) -> bool:
    kind = _sniff_kind(source)
    if kind == "video":
        return True
    if kind == "image":
        try:
            with Image.open(source) as image:
                return bool(getattr(image, "is_animated", False))
        except Exception:
            return False
    return source.suffix.lower() in ANIMATED_SUFFIXES


def _load_image(source: Path) -> Image.Image | None:
    try:
        image = Image.open(source)
        if getattr(image, "is_animated", False):
            image.seek(0)
        return image.convert("RGBA")
    except Exception:
        return None


def _fit_square(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    if width == 0 or height == 0:
        raise ValueError("imagen vacía")
    scale = min(size / width, size / height)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = image.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - new_size[0]) // 2, (size - new_size[1]) // 2)
    canvas.paste(resized, offset, resized)
    return canvas


def _run_webp_ffmpeg(
    source: Path,
    destination: Path,
    config: Config,
    fps: int,
    quality: int,
    seconds: float | None = None,
) -> bool:
    size = config.size
    duration = config.max_anim_seconds if seconds is None else seconds
    video_filter = (
        f"fps={fps},scale={size}:{size}:force_original_aspect_ratio=decrease,"
        f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
    )
    base = ["ffmpeg", "-y", "-loglevel", "error", "-t", str(duration)]
    if source.is_dir():
        base += ["-framerate", str(fps)]
    base += [
        "-i",
        str(source / "seq_%04d.png") if source.is_dir() else str(source),
        "-vf",
        video_filter,
        "-an",
        "-vcodec",
        "libwebp_anim",
        "-lossless",
        "0",
        "-compression_level",
        "4",
        "-q:v",
        str(quality),
        "-loop",
        "0",
        "-preset",
        "default",
        "-pix_fmt",
        "yuva420p",
        str(destination),
    ]
    if _run(base):
        return True
    fallback = list(base)
    fallback[fallback.index("libwebp_anim")] = "libwebp"
    return _run(fallback)


def _run(command: list[str]) -> bool:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=180
        )
    except Exception:
        return False
    return result.returncode == 0


def probe_duration(source: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout or "{}")
        return float(data["format"]["duration"])
    except Exception:
        return None


def _sniff_kind(source: Path) -> str:
    try:
        head = source.read_bytes()[:16]
    except Exception:
        return "unknown"
    if head[:3] == b"\xff\xd8\xff":
        return "image"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image"
    if head[:4] == b"GIF8":
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp":
        return "video"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "video"
    return "unknown"
