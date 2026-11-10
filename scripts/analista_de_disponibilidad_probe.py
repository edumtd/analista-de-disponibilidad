"""Prueba de viabilidad: abre cada URL de products.yaml y guarda evidencia.

Corre igual en GitHub Actions y en local:

    python scripts/analista_de_disponibilidad_probe.py [--products products.yaml] [--out probe_output]

Por cada producto guarda en <out>/<NN>/: page.html, screenshot.png y meta.json
(código HTTP, título, veredicto). Si existe GITHUB_STEP_SUMMARY, escribe ahí
una tabla con el resultado; si no, la imprime en consola.

Comportamiento cortés: un producto a la vez, 5-15 s aleatorios entre productos,
un solo contexto de navegador y sin reintentos.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
NAV_TIMEOUT_MS = 45_000
BLOCK_PATTERNS = [
    r"captcha",
    r"\brobot\b",
    r"press\s*&\s*hold",
    r"mant[eé]n presionado",
    r"verifica(r)? que eres (un )?humano",
    r"access denied",
    r"acceso denegado",
    r"px-captcha",
    r"perimeterx",
    r"are you a human",
]
MIN_TEXT_CHARS = 500


def classify(status: int | None, title: str, html: str, text: str) -> tuple[str, list[str]]:
    """Devuelve ("ok" | "blocked" | "empty" | "error", motivos)."""
    reasons: list[str] = []
    if status is None:
        return "error", ["sin respuesta HTTP"]
    if status in (403, 429) or status >= 500:
        reasons.append(f"HTTP {status}")
    haystack = f"{title}\n{text}".lower()
    for pat in BLOCK_PATTERNS:
        if re.search(pat, haystack, re.IGNORECASE):
            reasons.append(f"texto coincide con /{pat}/")
    if reasons:
        return "blocked", reasons
    if len(text.strip()) < MIN_TEXT_CHARS:
        return "empty", [f"solo {len(text.strip())} caracteres de texto visible"]
    if status >= 400:
        return "error", [f"HTTP {status}"]
    return "ok", []


DEFAULT_SELLER = "The Fragrance"


def load_config(path: Path) -> tuple[str, list[dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("seller_name") or DEFAULT_SELLER, list(data.get("products") or [])


def probe_one(page, url: str, out_dir: Path, seller: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {"url": url, "checked_at": datetime.now(timezone.utc).isoformat()}
    xhr: list[dict] = []

    def on_response(resp):
        if resp.request.resource_type in ("xhr", "fetch"):
            xhr.append(
                {
                    "url": resp.url,
                    "status": resp.status,
                    "content_type": resp.headers.get("content-type", ""),
                }
            )

    page.on("response", on_response)
    status = None
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        status = resp.status if resp else None
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightError:
            pass  # algunas páginas nunca quedan "idle"; seguimos con lo que haya
    except PlaywrightError as exc:
        meta["navigation_error"] = str(exc).splitlines()[0]
    finally:
        page.remove_listener("response", on_response)

    title, html, text = "", "", ""
    try:
        title = page.title()
        html = page.content()
        text = page.inner_text("body") if html else ""
    except PlaywrightError as exc:
        meta["read_error"] = str(exc).splitlines()[0]

    (out_dir / "page.html").write_text(html, encoding="utf-8")
    try:
        page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
    except PlaywrightError as exc:
        meta["screenshot_error"] = str(exc).splitlines()[0]

    verdict, reasons = classify(status, title, html, text)
    meta.update(
        {
            "http_status": status,
            "title": title,
            "verdict": verdict,
            "reasons": reasons,
            "html_bytes": len(html.encode("utf-8")),
            "visible_text_chars": len(text.strip()),
            "has_next_data": 'id="__NEXT_DATA__"' in html,
            # Solo indica si el vendedor aparece en la página; quién vende cada
            # oferta se resuelve en el paso 2 con los datos estructurados.
            "seller_in_text": text.lower().count(seller.lower()),
            "seller_in_html": html.lower().count(seller.lower()),
            "xhr_responses": xhr,
        }
    )
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def render_summary(results: list[dict], seller: str) -> str:
    icons = {"ok": "✅", "blocked": "⛔", "empty": "⚠️", "error": "❌"}
    lines = [
        "## Analista de disponibilidad · probe",
        "",
        f"| # | Producto | HTTP | Veredicto | `__NEXT_DATA__` | ¿{seller}? (texto/HTML) | Título | Motivos |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").replace("|", "\\|")[:80]
        reasons = "; ".join(r.get("reasons") or []) or r.get("navigation_error", "")
        lines.append(
            f"| {i:02d} | {r['name']} | {r.get('http_status')} | "
            f"{icons.get(r['verdict'], '')} {r['verdict']} | "
            f"{'sí' if r.get('has_next_data') else 'no'} | "
            f"{r.get('seller_in_text', 0)}/{r.get('seller_in_html', 0)} | "
            f"{title} | {reasons.replace('|', '/')} |"
        )
    ok = sum(1 for r in results if r["verdict"] == "ok")
    lines += ["", f"**{ok}/{len(results)} páginas cargaron bien.**", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", default="products.yaml", type=Path)
    parser.add_argument("--out", default="probe_output", type=Path)
    parser.add_argument("--headed", action="store_true", help="mostrar el navegador (solo local)")
    args = parser.parse_args(argv)
    # La consola de Windows usa cp1252 por defecto y no puede imprimir emojis/acentos.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    seller, products = load_config(args.products)
    if not products:
        print(f"No hay productos en {args.products}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="es-MX",
            timezone_id="America/Mexico_City",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        for i, product in enumerate(products, 1):
            if i > 1:
                delay = random.uniform(5, 15)
                print(f"  esperando {delay:.1f} s…")
                time.sleep(delay)
            name = product.get("name", f"producto {i}")
            print(f"[{i}/{len(products)}] {name}: {product['url']}")
            meta = probe_one(page, product["url"], args.out / f"{i:02d}", seller)
            meta["name"] = name
            results.append(meta)
            print(f"  HTTP {meta['http_status']} · {meta['verdict']} · {meta['title'][:60]!r}")
        context.close()
        browser.close()

    (args.out / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = render_summary(results, seller)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    print(summary)
    # El probe siempre termina en verde: el veredicto va en el summary y en los artifacts.
    return 0


if __name__ == "__main__":
    sys.exit(main())
