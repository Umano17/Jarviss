"""Pubblicazione delle demo con un link da mandare al titolare.

Due strade:
  1. Con NETLIFY_TOKEN nel file .env: Jarvis crea il sito su Netlify (una volta) e carica la demo: link tipo
     https://salicornia-jesolo-demo-ab12.netlify.app  (ogni nuova pubblicazione aggiorna lo stesso link).
  2. Senza token: Jarvis prepara uno zip in demo/<slug>/pubblica-<slug>.zip da trascinare su
     https://app.netlify.com/drop  (gratis, link pronto in pochi secondi).

Si pubblica solo una BOZZA: la pagina deve avere la fascia "bozza dimostrativa" e il meta noindex.
Pubblicare è un'azione verso l'esterno: Jarvis lo fa solo su richiesta esplicita di Jonatan.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import siti

API = "https://api.netlify.com/api/v1"


def _cartella(slug: str, versione: str) -> Path:
    base = siti.CARTELLA / slug
    return base / "personalizzata" if versione == "personalizzata" else base


def _file_da_pubblicare(slug: str, versione: str) -> list[tuple[Path, str]]:
    c = _cartella(slug, versione)
    f = [(c / "index.html", "index.html")]
    if versione == "personalizzata":
        f += [(p, f"img/{p.name}") for p in sorted((c / "img").glob("*.webp"))] if (c / "img").is_dir() else []
    return f


def _controlla(html: str) -> str:
    h = html.lower()
    if "noindex" not in h:
        return "La pagina non ha il meta noindex: non la pubblico."
    if "bozza" not in h and "draft" not in h:
        return "La pagina non ha la fascia «bozza dimostrativa»: non la pubblico finché il titolare non conferma."
    if "</html>" not in h:
        return "La pagina è incompleta: va rifatta prima di pubblicarla."
    return ""


def _zip(slug: str, versione: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for sorgente, nome in _file_da_pubblicare(slug, versione):
            z.write(sorgente, nome)
        # niente indicizzazione nemmeno a livello di server
        z.writestr("_headers", "/*\n  X-Robots-Tag: noindex, nofollow\n")
    return buf.getvalue()


def _richiesta(metodo: str, percorso: str, token: str, dati: bytes | None = None, tipo: str = "application/json") -> dict:
    req = urllib.request.Request(API + percorso, data=dati, method=metodo,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": tipo,
                                          "User-Agent": "Jarvis/3.5"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def pubblica(slug: str, versione: str = "auto") -> dict:
    slug = siti.slug(slug)
    if not (siti.CARTELLA / slug).is_dir():
        return {"errore": "Demo non trovata."}
    if versione == "auto":
        versione = "personalizzata" if (siti.CARTELLA / slug / "personalizzata" / "index.html").exists() else "demo"
    pagina = _cartella(slug, versione) / "index.html"
    if not pagina.exists():
        return {"errore": "La demo non ha ancora la pagina index.html."}
    problema = _controlla(pagina.read_text(encoding="utf-8", errors="ignore"))
    if problema:
        return {"errore": problema}
    dati = _zip(slug, versione)
    meta_f = siti.CARTELLA / slug / "pubblicazione.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    token = os.getenv("NETLIFY_TOKEN", "").strip()
    if not token:
        z = siti.CARTELLA / slug / f"pubblica-{slug}.zip"
        z.write_bytes(dati)
        return {"modo": "manuale", "zip": str(z), "versione": versione,
                "istruzioni": "Apri https://app.netlify.com/drop e trascina il file " + z.name +
                              " (cartella della demo): in pochi secondi hai il link. Per farlo fare a Jarvis, "
                              "aggiungi NETLIFY_TOKEN nel file .env."}
    try:
        if not meta.get("site_id"):
            nome = re.sub(r"[^a-z0-9-]", "", f"{slug}-demo-{secrets.token_hex(2)}")[:60]
            s = _richiesta("POST", "/sites", token, json.dumps({"name": nome}).encode())
            meta = {"site_id": s["id"], "url": s.get("ssl_url") or s.get("url")}
        d = _richiesta("POST", f"/sites/{meta['site_id']}/deploys", token, dati, "application/zip")
        meta.update(ultimo_deploy=d.get("id"), versione=versione)
        meta_f.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    except urllib.error.HTTPError as e:
        return {"errore": f"Netlify ha risposto {e.code}: controlla NETLIFY_TOKEN nel file .env."}
    except Exception as e:
        return {"errore": f"Pubblicazione non riuscita: {e}"}
    _collega_cliente(slug, meta["url"])
    return {"modo": "netlify", "url": meta["url"], "versione": versione}


def _collega_cliente(slug: str, url: str) -> None:
    try:
        import produttivita
        produttivita.sincronizza_demo()
        c = next((x for x in produttivita.clienti() if x.get("demo_slug") == slug), None)
        if c:
            produttivita.aggiorna_cliente(c["id"], link_demo=url, nota=f"Demo pubblicata: {url}")
    except Exception as e:
        print("Pubblicazione, cliente:", e)


def link(slug: str) -> str:
    f = siti.CARTELLA / siti.slug(slug) / "pubblicazione.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("url", "")
    except (OSError, ValueError):
        return ""
