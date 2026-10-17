from __future__ import annotations

import argparse
from dataclasses import replace

from .capture import capture, login
from .config import BASE_DIR, Config
from .convert import convert_all
from .export import build_pack, serve_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sticker_extractor",
        description="Extrae los stickers guardados en TikTok y los prepara para WhatsApp.",
    )
    parser.add_argument(
        "command",
        choices=["login", "capture", "convert", "export", "run", "all"],
        help=(
            "login: inicia sesión en TikTok | capture: descarga stickers | "
            "convert: los pasa a WebP 512x512 | export: crea el paquete y el QR | "
            "run: capture + convert + export | all: convert + export"
        ),
    )
    parser.add_argument("--headless", action="store_true", help="Navegador sin ventana")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Guarda un diagnóstico del DOM (para revisar por qué faltan stickers)",
    )
    parser.add_argument("--scroll", type=int, default=15, help="Rondas de desplazamiento")
    parser.add_argument("--delay", type=float, default=0.8, help="Segundos entre scrolls")
    parser.add_argument("--start-url", default=None, help="URL de un chat concreto")
    parser.add_argument("--port", type=int, default=8000, help="Puerto del servidor local")
    parser.add_argument("--no-serve", action="store_true", help="No arrancar el servidor")
    parser.add_argument("--max-seconds", type=float, default=6.0, help="Duración máxima de un sticker animado")
    parser.add_argument("--static-kb", type=int, default=100, help="Tamaño máximo de un sticker fijo (KB)")
    parser.add_argument("--animated-kb", type=int, default=500, help="Tamaño máximo de un sticker animado (KB)")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Borra stickers_raw/stickers_ready/pack antes de empezar",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    return replace(
        Config(),
        headless=args.headless,
        debug=args.debug,
        scroll_rounds=args.scroll,
        scroll_delay=args.delay,
        port=args.port,
        serve=not args.no_serve,
        max_anim_seconds=args.max_seconds,
        static_max_bytes=args.static_kb * 1024,
        animated_max_bytes=args.animated_kb * 1024,
    )


def clean_workdirs(config: Config) -> None:
    cleared = 0
    for directory in (config.raw_dir, config.ready_dir, config.pack_dir):
        for item in directory.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()
                cleared += 1
            elif item.is_dir():
                import shutil

                shutil.rmtree(item)
                cleared += 1
    if cleared:
        print(f"Limpieza: {cleared} elementos borrados.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    config.ensure_dirs()
    print(f"Carpeta de trabajo: {BASE_DIR}")

    if args.clean:
        clean_workdirs(config)

    if args.command == "login":
        login(config)
    elif args.command == "capture":
        capture(config, args.start_url)
    elif args.command == "convert":
        convert_all(config)
    elif args.command == "export":
        build_pack(config)
        if config.serve:
            serve_pack(config)
    elif args.command in ("run", "all"):
        if args.command == "run":
            capture(config, args.start_url)
        convert_all(config)
        build_pack(config)
        if config.serve:
            serve_pack(config)
    return 0
