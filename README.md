# Sticker Extractor — TikTok → WhatsApp

Descarga los stickers de un chat de TikTok (Mensajes directos) y los arma en
paquetes listos para WhatsApp (`.wastickers`), sin tener que agregarlos uno por uno.

Funciona en **Windows**, **Linux** y **macOS**. Funciona en Windows/Mac/Linux.

---

## Requisitos

- **Python 3.10 o superior** (con `venv`).
- **FFmpeg** (necesario para los stickers animados).
  - Windows: descarga la build de https://www.gyan.dev/ffmpeg/builds/ , descomprime
    y agrega la carpeta `bin` al **PATH**. Para comprobar: abre una terminal y
    escribe `ffmpeg -version`.
  - Linux: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`

> Nota: los stickers **⭐ Favoritos** existen solo en la app móvil de TikTok; la web
> no los muestra. Por eso el truco es: desde el móvil, envía los stickers que quieras
> a un chat (tuyo o de un amigo), y luego este programa los captura desde la web.

---

## Instalación (Windows)

Abre **PowerShell** en la carpeta del proyecto y ejecuta:

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
```

## Instalación (Linux / macOS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

---

## Uso

Los comandos, en Windows usa `.venv\Scripts\python` y en Linux/macOS
`.venv/bin/python`.

### 1. Iniciar sesión en TikTok (solo la primera vez)

```
.venv\Scripts\python -m sticker_extractor login
```

Se abre un navegador. Inicia sesión como siempre. Cuando estés dentro, vuelve a la
terminal y pulsa **Enter**. La sesión queda guardada.

### 2. Extraer y preparar los stickers

```
.venv\Scripts\python -m sticker_extractor run
```

1. Se abre el navegador en **Mensajes**.
2. Entra al chat que contiene los stickers.
3. Sube por el historial hasta arriba (rueda del ratón sobre los mensajes).
4. Vuelve a la terminal y pulsa **Enter**.
5. El programa descarga, convierte y arma los paquetes.

Al terminar aparece un **código QR** y una dirección tipo `http://192.168.x.x:8000/`.

### 3. Pasar los paquetes al móvil

1. Con el móvil en la **misma WiFi**, escanea el QR (o abre la dirección).
2. Descarga los archivos **`.wastickers`** (botones azules).
3. Al abrir un `.wastickers`, elige **Sticker Maker** y luego **Add to WhatsApp**.
   Cada paquete se agrega completo de una sola vez (máximo 30 stickers por paquete).

Para detener el servidor: `Ctrl + C`.

---

## Comandos por fases

```
python -m sticker_extractor login     # iniciar sesión
python -m sticker_extractor capture   # solo descargar
python -m sticker_extractor convert   # solo convertir a WebP 512x512
python -m sticker_extractor export    # empaquetar + servir + QR
python -m sticker_extractor run       # capture + convert + export
python -m sticker_extractor export --no-serve   # empaquetar sin servidor
```

Opciones útiles: `--clean` (borra lo anterior), `--scroll 25` (más historial),
`--debug` (guarda un diagnóstico del chat).

## Límites de WhatsApp (ya aplicados)

- Sticker: 512×512, fondo transparente, WebP.
- Fijo: ≤ 100 KB. Animado: ≤ 500 KB, ≤ 6 s.
- Paquete: 3 a 30 stickers. No se mezclan fijos con animados.

## Uso personal

Herramienta para respaldar **tus propios** stickers. Respeta los derechos de autor de
los creadores.
