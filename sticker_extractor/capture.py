from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .config import (
    SESSION_COOKIES,
    TIKTOK_HOME,
    TIKTOK_LOGIN,
    TIKTOK_MESSAGES,
    Config,
)

MEDIA_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.I)
STICKER_FORMATS = (".awebp", ".webp", ".webm", ".mp4", ".gif", ".png")

STICKER_JSON_KEYS = ("url", "sticker", "static_url", "animate_url", "emoticon")
STICKER_PATH_HINTS = (
    "sticker",
    "dm-sticker",
    "dm_sticker",
    "dhq7zx4c1p",
    "emoji",
    "emoticon",
)

SKIP_HINTS = ("avatar", "avt", "/avt/", "profile", "music")

CONTENT_TYPES = {
    "image/webp": ".webp",
    "image/webp;charset=utf-8": ".webp",
    "image/gif": ".gif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

DOM_COLLECT_JS = r"""
() => {
  const urls = new Set();
  const push = (u) => {
    if (u && typeof u === 'string' && u.startsWith('http')) urls.add(u);
  };
  const pushSrcset = (s) => {
    if (s) s.split(',').forEach((p) => push(p.trim().split(' ')[0]));
  };
  const pushBackground = (v) => {
    if (!v || v === 'none') return;
    const matches = v.match(/url\((['"]?)(.*?)\1\)/g);
    if (matches) {
      matches.forEach((entry) => {
        push(entry.replace(/^url\((['"]?)/, '').replace(/(['"]?)\)$/, ''));
      });
    }
  };
  document.querySelectorAll('img').forEach((el) => {
    push(el.currentSrc || el.src);
    pushSrcset(el.srcset);
    push(el.getAttribute('data-src'));
    push(el.getAttribute('data-original'));
  });
  document.querySelectorAll('video').forEach((el) => {
    push(el.currentSrc || el.src);
    push(el.getAttribute('data-src'));
  });
  document.querySelectorAll('source').forEach((el) => {
    push(el.src);
    pushSrcset(el.srcset);
  });
  document.querySelectorAll('*').forEach((el) => {
    const styleAttr = el.getAttribute && el.getAttribute('style');
    if (styleAttr && styleAttr.indexOf('url(') !== -1) pushBackground(styleAttr);
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    if (/sticker|emoji|image|note|img/i.test(cls)) {
      try { pushBackground(getComputedStyle(el).backgroundImage); } catch (e) {}
    }
  });
  return Array.from(urls);
}
"""


DEBUG_SCAN_JS = r"""
() => {
  const out = [];
  const grab = (el) => (el.currentSrc || el.src || el.getAttribute('data-src') || '').toString();
  document.querySelectorAll('img, video, source').forEach((el) => {
    const src = grab(el);
    if (!src) return;
    const parents = [];
    let node = el;
    for (let i = 0; i < 4 && node; i++) {
      const cls = node.className && node.className.toString ? node.className.toString() : '';
      const e2e = node.getAttribute ? (node.getAttribute('data-e2e') || '') : '';
      parents.push(`${node.tagName.toLowerCase()}[${e2e}|${cls.slice(0, 80)}]`);
      node = node.parentElement;
    }
    out.push({ tag: el.tagName.toLowerCase(), src: src, parents: parents });
  });
  document.querySelectorAll('*').forEach((el) => {
    const style = el.getAttribute && el.getAttribute('style');
    if (style && style.indexOf('url(') !== -1) {
      const m = style.match(/url\(['"]?(.*?)['"]?\)/);
      if (m && m[1]) {
        const cls = el.className && el.className.toString ? el.className.toString() : '';
        out.push({ tag: el.tagName.toLowerCase(), src: m[1], parents: ['inline-bg:' + cls.slice(0, 80)] });
      }
    }
  });
  return out;
}
"""


def _dump_debug(page: Page, config: Config) -> None:
    try:
        entries = page.evaluate(DEBUG_SCAN_JS)
    except Exception as exc:
        print(f"No se pudo escribir el diagnóstico: {exc}")
        return
    target = config.raw_dir / "debug_media.json"
    target.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Diagnóstico guardado en {target} ({len(entries)} elementos)")
    _print_debug_summary(entries)


def _print_debug_summary(entries: list[dict]) -> None:
    domains: dict[str, int] = {}
    flagged: list[dict] = []
    for item in entries:
        src = item.get("src", "")
        host = urlparse(src).netloc
        domains[host] = domains.get(host, 0) + 1
        low = src.lower()
        if "ibyteimg" in low or "sticker" in low or "emoticon" in low:
            flagged.append(item)

    print("\n--- RESUMEN (copia y pega esto) ---")
    print("Dominios encontrados:")
    for host, count in sorted(domains.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {host or '(sin host)'}")
    print(f"\nElementos con 'sticker'/'webp'/'ibyteimg': {len(flagged)}")
    seen: set[str] = set()
    for item in flagged[:40]:
        key = f"{item['tag']} {' > '.join(item.get('parents', []))}"
        if key in seen:
            continue
        seen.add(key)
        print(f"  - {key}")
        print(f"      {item['src'][:160]}")
    print("--- FIN RESUMEN ---\n")


@dataclass
class Candidate:
    url: str
    source: str


@dataclass
class Collector:
    found: dict[str, Candidate] = field(default_factory=dict)

    def add(self, url: str, source: str) -> None:
        url = url.strip().replace("\\u002F", "/").replace("\\/", "/")
        if not url.startswith("http"):
            return
        if not _looks_like_sticker(url):
            return
        key = _normalize(url)
        if key not in self.found:
            self.found[key] = Candidate(url=url, source=source)

    def urls(self) -> list[str]:
        return [c.url for c in self.found.values()]


def _looks_like_sticker(url: str) -> bool:
    low = url.lower()
    if any(hint in low for hint in SKIP_HINTS):
        return False
    path = urlparse(low).path
    if not path.endswith(STICKER_FORMATS):
        return False
    if "tiktok-dm-sticker" in low:
        return True
    if "ibyteimg.com" in low or "tiktokcdn" in low or "tiktok.com/" in low:
        return any(hint in low for hint in STICKER_PATH_HINTS)
    return False


def _normalize(url: str) -> str:
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


def is_logged_in(context: BrowserContext) -> bool:
    names = {c.get("name") for c in context.cookies(TIKTOK_HOME)}
    return bool(names.intersection(SESSION_COOKIES))


def login(config: Config) -> None:
    config.ensure_dirs()
    with sync_playwright() as pw:
        context = _launch(pw, config)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TIKTOK_LOGIN, wait_until="domcontentloaded")
        print("\nInicia sesión en la ventana del navegador (QR, correo o teléfono).")
        print("Cuando termines, vuelve aquí y pulsa Enter.\n")
        input("Enter cuando hayas iniciado sesión... ")
        if is_logged_in(context):
            print("Sesión guardada. Ya puedes ejecutar 'capture'.")
        else:
            print("No detecté la sesión. Vuelve a intentarlo con 'login'.")
        context.close()


def capture(config: Config, start_url: str | None = None) -> list[Path]:
    config.ensure_dirs()
    collector = Collector()
    with sync_playwright() as pw:
        context = _launch(pw, config)
        if not is_logged_in(context):
            print("No hay sesión guardada. Ejecuta primero: python -m sticker_extractor login")
            context.close()
            return []

        page = context.pages[0] if context.pages else context.new_page()
        _attach_network_collector(page, collector)
        page.goto(start_url or TIKTOK_MESSAGES, wait_until="domcontentloaded")
        _print_capture_instructions()
        input("Enter cuando tengas abierto el chat con los stickers... ")

        _autoscroll(page, config, collector)
        _collect_from_dom(page, collector)
        if config.debug:
            _dump_debug(page, config)

        urls = collector.urls()
        print(f"\nEncontrados {len(urls)} stickers candidatos. Descargando...")
        saved = _download_all(context, urls, config.raw_dir)
        print(f"Guardados {len(saved)} archivos en {config.raw_dir}")
        context.close()
    return saved


def _launch(pw: Playwright, config: Config) -> BrowserContext:
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(config.profile_dir),
        headless=config.headless,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def _print_capture_instructions() -> None:
    print("\nEn la ventana del navegador:")
    print("  1. Abre Mensajes (DM) y entra a la conversación que contiene los stickers.")
    print("  2. Sube por el historial hasta arriba para que TikTok cargue los mensajes.")
    print("     (Con la rueda del ratón sobre la lista de mensajes).")
    print("  Nota: la pestaña de stickers ⭐ Favoritos NO existe en la web; solo en la app.")
    print("  Si aún no tienes los stickers en un chat, mándalos desde el móvil a este chat.")
    print("")


def _attach_network_collector(page: Page, collector: Collector) -> None:
    def on_response(response) -> None:
        try:
            headers = response.headers
        except Exception:
            return
        content_type = headers.get("content-type", "")
        if "json" not in content_type:
            return
        if "/api/" not in response.url and "sticker" not in response.url.lower():
            return
        try:
            payload = response.json()
        except Exception:
            return
        _walk_json(payload, collector)

    page.on("response", on_response)


def _walk_json(node, collector: Collector) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_low = key.lower()
            if isinstance(value, str) and (
                "url" in key_low or any(h in key_low for h in STICKER_JSON_KEYS)
            ):
                for match in MEDIA_URL_RE.findall(value):
                    collector.add(match, "network")
            else:
                _walk_json(value, collector)
    elif isinstance(node, list):
        for item in node:
            _walk_json(item, collector)
    elif isinstance(node, str):
        for match in MEDIA_URL_RE.findall(node):
            collector.add(match, "network")


def _collect_from_dom(page: Page, collector: Collector) -> None:
    try:
        urls = page.evaluate(DOM_COLLECT_JS)
    except Exception:
        return
    for url in urls:
        collector.add(url, "dom")


def _autoscroll(page: Page, config: Config, collector: Collector) -> None:
    print("Cargando historial (desplazando)...")
    _collect_from_dom(page, collector)
    for _ in range(max(1, config.scroll_rounds)):
        try:
            page.mouse.move(640, 450)
            page.mouse.wheel(0, -2500)
        except Exception:
            break
        page.wait_for_timeout(int(config.scroll_delay * 1000))
        _collect_from_dom(page, collector)


def _download_all(
    context: BrowserContext, urls: list[str], raw_dir: Path
) -> list[Path]:
    saved: list[Path] = []
    manifest: dict[str, str] = {}
    for index, url in enumerate(urls, start=1):
        try:
            response = context.request.get(
                url, headers={"Referer": TIKTOK_HOME, "Origin": "https://www.tiktok.com"}
            )
        except Exception as exc:
            print(f"  [{index}/{len(urls)}] error: {exc}")
            continue
        if not response.ok:
            print(f"  [{index}/{len(urls)}] HTTP {response.status}")
            continue
        body = response.body()
        if not body:
            continue
        extension = _extension_for(response.headers.get("content-type", ""), url)
        digest = hashlib.sha1(body).hexdigest()[:12]
        destination = raw_dir / f"{digest}{extension}"
        if destination.exists():
            continue
        destination.write_bytes(body)
        manifest[destination.name] = url
        saved.append(destination)
        print(f"  [{index}/{len(urls)}] {destination.name} ({len(body)} bytes)")
    (raw_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return saved


def _extension_for(content_type: str, url: str) -> str:
    clean = content_type.split(";")[0].strip().lower()
    if clean in CONTENT_TYPES:
        return CONTENT_TYPES[clean]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in STICKER_FORMATS:
        return suffix
    return ".bin"
