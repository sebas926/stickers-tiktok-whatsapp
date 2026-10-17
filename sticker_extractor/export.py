from __future__ import annotations

import functools
import shutil
import socket
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from .config import PACK_MAX_STICKERS, Config
from .convert import make_tray

GALLERY_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Mis stickers de TikTok</title>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; background:#111; color:#eee; }}
  header {{ padding:16px; position:sticky; top:0; background:#181818; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
  h1 {{ font-size:16px; margin:0 8px 0 0; }}
  a.button {{ background:#25D366; color:#062; padding:10px 16px; border-radius:999px; text-decoration:none; font-weight:600; }}
  a.pack {{ background:#3b82f6; color:#fff; }}
  main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); gap:12px; padding:16px; }}
  figure {{ margin:0; background:#1d1d1d; border-radius:12px; padding:8px; }}
  img {{ width:100%; aspect-ratio:1; object-fit:contain; background:#000; border-radius:8px; }}
  figcaption {{ font-size:11px; color:#9a9a9a; text-align:center; margin-top:6px; }}
</style>
</head>
<body>
<header>
  <h1>{count} stickers listos</h1>
  <a class="button" href="stickers-pack.zip" download>Descargar todo (.zip)</a>
  {packs}
</header>
<main>
{items}
</main>
</body>
</html>
"""

ITEM_TEMPLATE = """  <figure>
    <img src="{name}" alt="{name}" loading="lazy" />
    <figcaption>{name}</figcaption>
  </figure>"""

PACK_LINK_TEMPLATE = """  <a class="button pack" href="{file}" download>{label}</a>"""


def build_pack(config: Config) -> int:
    config.ensure_dirs()
    all_stickers = sorted(config.ready_dir.glob("*.webp"))
    stickers = []
    for path in all_stickers:
        if _exceeds_limit(path, config):
            print(f"  Omitido (fuera de tamaño): {path.name}")
            continue
        stickers.append(path)
    if not stickers:
        print(f"No hay stickers convertidos en {config.ready_dir}")
        return 0

    for existing in config.pack_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    items = []
    count = 0
    for index, source in enumerate(stickers, start=1):
        count += 1
        name = f"sticker_{index:03d}.webp"
        shutil.copy2(source, config.pack_dir / name)
        items.append(ITEM_TEMPLATE.format(name=name))

    tray = config.pack_dir / "tray.png"
    make_tray(stickers[0], tray, config)

    pack_files = _build_wastickers(config, stickers, tray)
    links = [
        PACK_LINK_TEMPLATE.format(file=path.name, label=label)
        for path, label in pack_files
    ]

    gallery = GALLERY_TEMPLATE.format(
        count=count, items="\n".join(items), packs="\n".join(links)
    )
    (config.pack_dir / "index.html").write_text(gallery, encoding="utf-8")

    with zipfile.ZipFile(config.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(config.pack_dir.iterdir()):
            if file.is_file() and file.name != "stickers-pack.zip":
                archive.write(file, file.name)
    shutil.copy2(config.zip_path, config.pack_dir / "stickers-pack.zip")

    print(f"Paquete con {count} stickers en {config.pack_dir}")
    for path, label in pack_files:
        print(f"  Pack: {path.name} ({label})")
    print(f"Zip: {config.zip_path}")
    return count


def _is_animated(path) -> bool:
    try:
        with Image.open(path) as image:
            return bool(getattr(image, "is_animated", False))
    except Exception:
        return False


def _exceeds_limit(path, config: Config) -> bool:
    limit = (
        config.animated_max_bytes if _is_animated(path) else config.static_max_bytes
    )
    return path.stat().st_size > limit


def _balanced_chunks(items: list, max_size: int) -> list[list]:
    if not items:
        return []
    total = len(items)
    group_count = -(-total // max_size)
    size = -(-total // group_count)
    return [items[i : i + size] for i in range(0, total, size)]


def _build_wastickers(config: Config, stickers, tray) -> list[tuple]:
    static = [p for p in stickers if not _is_animated(p)]
    animated = [p for p in stickers if _is_animated(p)]

    built: list[tuple] = []
    for kind_label, kind_slug, group in (
        ("", "static", static),
        ("animados ", "anim", animated),
    ):
        chunks = _balanced_chunks(group, PACK_MAX_STICKERS)
        for number, chunk in enumerate(chunks, start=1):
            label = f"{kind_label}{number}"
            filename = f"{kind_slug}-{number}.wastickers"
            target = config.pack_dir / filename
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("title.txt", f"{config.pack_name} {label}".strip())
                archive.writestr("author.txt", config.pack_author)
                archive.write(tray, "cover.png")
                for index, sticker in enumerate(chunk, start=1):
                    archive.write(sticker, f"sticker_{index:02d}.webp")
            built.append((target, label))
    return built


def lan_ip() -> str:
    candidates: list[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        candidates.append(sock.getsockname()[0])
    except Exception:
        pass
    finally:
        sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except Exception:
        pass
    for address in candidates:
        if address and not address.startswith("127."):
            return address
    return candidates[0] if candidates else "127.0.0.1"


def serve_pack(config: Config) -> None:
    if not (config.pack_dir / "index.html").exists():
        print("Primero construye el paquete con 'export'.")
        return

    url = f"http://{lan_ip()}:{config.port}/"
    _print_qr(url, config)

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(config.pack_dir))
    server = ThreadingHTTPServer(("0.0.0.0", config.port), handler)
    print(f"\nServidor en {url}")
    print("Abre esa dirección en el móvil (misma WiFi) y descarga los stickers.")
    print("Pulsa Ctrl+C para parar.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


def _print_qr(url: str, config: Config) -> None:
    try:
        import qrcode
    except ImportError:
        print(f"(Instala 'qrcode' para ver el código QR). URL: {url}")
        return

    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

    image = qr.make_image(fill_color="black", back_color="white")
    target = config.pack_dir / "qr.png"
    image.save(target)
    print(f"QR guardado en {target}")
