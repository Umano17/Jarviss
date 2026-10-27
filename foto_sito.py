"""Foto nei siti: inserisce, ruota, taglia e comprime le foto dentro una demo personalizzata.

Come si usa (dentro ~/jarvis, con il venv attivo):
    python foto_sito.py salicornia-jesolo            # applica le foto
    python foto_sito.py salicornia-jesolo --elenco   # mostra gli spazi foto e cosa c'è dentro

Dove mettere le foto:  demo/<slug>/foto-da-inserire/
  - Il nome del file decide dove va: "hero.jpg" va nello spazio "hero", "piatto-2.heic" nello spazio "piatto-2".
  - Le foto con nomi qualsiasi (IMG_1234.jpg) riempiono gli spazi ancora vuoti, in ordine,
    preferendo quelli con la stessa forma (orizzontale/verticale).
  - Vanno bene JPG, PNG, WEBP e anche HEIC dell'iPhone (convertite con lo strumento del Mac "sips").

Cosa fa da solo:
  - raddrizza la foto (rotazione dell'iPhone), toglie i dati GPS e personali (EXIF);
  - taglia nella forma dello spazio scegliendo la zona più "piena" (dettagli, non cielo o muro vuoto);
  - crea due misure (telefono e computer) in WebP leggero;
  - scrive demo/<slug>/personalizzata/index.html con le foto al loro posto.

Se un taglio non ti piace: in demo/<slug>/foto.json cambia "fuoco" di quella foto
("alto", "basso", "sinistra", "destra", "centro" oppure "auto") e rilancia.

Gli spazi foto nella pagina sono gli elementi con  data-foto="nome"  e  data-formato="16:9"
(un <img>, oppure un altro elemento che riceve la foto come sfondo).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageFilter, ImageOps, ImageStat
except ImportError:  # messaggio chiaro invece di un errore tecnico
    print("Manca la libreria per le immagini. Nel Terminale, dentro ~/jarvis:  source venv/bin/activate && pip install pillow")
    sys.exit(1)

BASE = Path(__file__).parent
ESTENSIONI = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}
LARGHEZZE = (800, 1600)        # telefono, computer
QUALITA = 80
FUOCHI = ("auto", "centro", "alto", "basso", "sinistra", "destra")

SPAZIO_RE = re.compile(r"<(?P<tag>[a-zA-Z0-9]+)(?P<attr>[^>]*?\bdata-foto\s*=\s*\"(?P<nome>[^\"]+)\"[^>]*)>", re.S)


# ---------------------------------------------------------------- spazi nella pagina

def _attr(attr: str, nome: str) -> str | None:
    m = re.search(r"\b" + re.escape(nome) + r"\s*=\s*\"([^\"]*)\"", attr)
    return m.group(1) if m else None


def _rapporto(formato: str | None) -> float:
    try:
        a, b = (formato or "16:9").replace("/", ":").split(":")
        return max(0.2, min(5.0, float(a) / float(b)))
    except ValueError:
        return 16 / 9


def spazi(html: str) -> list[dict]:
    """Gli spazi foto della pagina, nell'ordine in cui compaiono."""
    out, visti = [], set()
    for m in SPAZIO_RE.finditer(html):
        nome = m.group("nome").strip()
        if nome in visti:
            continue
        visti.add(nome)
        formato = _attr(m.group("attr"), "data-formato") or "16:9"
        out.append({"nome": nome, "tag": m.group("tag").lower(), "formato": formato,
                    "rapporto": _rapporto(formato), "descrizione": _attr(m.group("attr"), "data-descrizione") or ""})
    return out


# ---------------------------------------------------------------- lettura e taglio

def apri(percorso: Path) -> Image.Image:
    """Apre la foto; le HEIC dell'iPhone vengono prima convertite in JPEG con sips (strumento del Mac)."""
    if percorso.suffix.lower() in (".heic", ".heif"):
        jpg = percorso.with_suffix(".convertita.jpg")
        if not jpg.exists():
            if not shutil.which("sips"):
                raise RuntimeError(f"{percorso.name}: le foto HEIC si convertono solo sul Mac (sips).")
            subprocess.run(["sips", "-s", "format", "jpeg", str(percorso), "--out", str(jpg)],
                           check=True, capture_output=True)
        percorso = jpg
    img = Image.open(percorso)
    img = ImageOps.exif_transpose(img)          # rotazione corretta
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":                        # trasparenza su fondo bianco
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    return img


def _finestra_migliore(img: Image.Image, w: int, h: int) -> tuple[int, int]:
    """Taglio "intelligente": cerca la finestra w×h con più dettagli (bordi), evitando cielo o pareti vuote."""
    W, H = img.size
    scala = 160 / max(W, H)
    piccola = img.convert("L").resize((max(1, int(W * scala)), max(1, int(H * scala))))
    bordi = piccola.filter(ImageFilter.FIND_EDGES)
    pw, ph = bordi.size
    fw, fh = max(1, int(w * scala)), max(1, int(h * scala))
    passi = 12
    migliore, pos = -1.0, (0, 0)
    for i in range(passi + 1):
        for j in range(passi + 1):
            x = int((pw - fw) * i / passi) if pw > fw else 0
            y = int((ph - fh) * j / passi) if ph > fh else 0
            energia = ImageStat.Stat(bordi.crop((x, y, x + fw, y + fh))).mean[0]
            # leggera preferenza per il centro e per il terzo superiore (piatti, volti, insegne)
            cx = abs((x + fw / 2) / pw - 0.5)
            cy = abs((y + fh / 2) / ph - 0.45)
            punteggio = energia * (1 - 0.35 * cx - 0.35 * cy)
            if punteggio > migliore:
                migliore, pos = punteggio, (x, y)
    return int(pos[0] / scala), int(pos[1] / scala)


def taglia(img: Image.Image, rapporto: float, fuoco: str = "auto") -> Image.Image:
    W, H = img.size
    if W / H > rapporto:            # troppo larga: taglio ai lati
        w, h = int(H * rapporto), H
    else:                           # troppo alta: taglio sopra/sotto
        w, h = W, int(W / rapporto)
    if fuoco == "auto":
        x, y = _finestra_migliore(img, w, h)
    else:
        x = {"sinistra": 0, "destra": W - w}.get(fuoco, (W - w) // 2)
        y = {"alto": 0, "basso": H - h}.get(fuoco, (H - h) // 2)
    x, y = max(0, min(x, W - w)), max(0, min(y, H - h))
    return img.crop((x, y, x + w, y + h))


def salva_misure(img: Image.Image, cartella: Path, nome: str) -> dict:
    """Salva le misure in WebP senza dati EXIF. Restituisce i percorsi relativi."""
    cartella.mkdir(parents=True, exist_ok=True)
    fatte = {}
    for larghezza in LARGHEZZE:
        if img.width < larghezza and fatte:
            continue                # non ingrandire oltre l'originale
        l = min(larghezza, img.width)
        copia = img.resize((l, round(l * img.height / img.width)), Image.LANCZOS)
        f = cartella / f"{nome}-{l}.webp"
        copia.save(f, "WEBP", quality=QUALITA, method=6)
        fatte[l] = f"img/{f.name}"
    return fatte


# ---------------------------------------------------------------- assegnazione foto → spazi

def _chiave(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")


def assegna(lista_spazi: list[dict], foto: list[Path], precedente: dict) -> dict:
    """Prima i nomi uguali allo spazio, poi le scelte già fatte (foto.json), poi riempie i vuoti per forma."""
    per_nome = {_chiave(s["nome"]): s for s in lista_spazi}
    scelte: dict[str, dict] = {}
    libere = []
    for f in foto:
        k = _chiave(f.stem)
        if k in per_nome and per_nome[k]["nome"] not in scelte:
            scelte[per_nome[k]["nome"]] = {"file": f.name, "fuoco": "auto"}
        else:
            libere.append(f)
    for nome, v in (precedente or {}).items():      # mantiene le scelte e i fuochi salvati
        if any(s["nome"] == nome for s in lista_spazi) and any(f.name == v.get("file") for f in foto):
            if nome not in scelte or scelte[nome]["file"] == v.get("file"):
                scelte[nome] = {"file": v["file"], "fuoco": v.get("fuoco", "auto") if v.get("fuoco") in FUOCHI else "auto"}
    usate = {v["file"] for v in scelte.values()}
    libere = [f for f in libere if f.name not in usate]

    def forma(f: Path) -> float:
        try:
            with Image.open(f) as im:
                im = ImageOps.exif_transpose(im)
                return im.width / im.height
        except Exception:
            return 1.5  # HEIC o file illeggibile prima della conversione: considerata orizzontale

    # prima gli spazi visibili nella pagina, poi quelli usati dallo script (meta, es. le foto del menu)
    for s in sorted(lista_spazi, key=lambda s: s["tag"] == "meta"):
        if s["nome"] in scelte or not libere:
            continue
        orizzontale = s["rapporto"] >= 1
        adatta = next((f for f in libere if (forma(f) >= 1) == orizzontale), libere[0])
        libere.remove(adatta)
        scelte[s["nome"]] = {"file": adatta.name, "fuoco": "auto"}
    return scelte


# ---------------------------------------------------------------- scrittura della pagina

def inserisci(html: str, nome: str, misure: dict, alt: str) -> str:
    grande = misure[max(misure)]
    srcset = ", ".join(f"{p} {l}w" for l, p in sorted(misure.items()))

    def sostituisci(m: re.Match) -> str:
        if m.group("nome").strip() != nome:
            return m.group(0)
        tag, attr = m.group("tag"), m.group("attr")
        if tag.lower() == "meta":      # foto usata dallo script della pagina (es. menu che cambia categoria)
            attr = re.sub(r"\scontent\s*=\s*\"[^\"]*\"", "", attr)
            return f'<{tag}{attr} content="{grande}">'
        if tag.lower() == "img":
            attr = re.sub(r"\s(src|srcset|sizes)\s*=\s*\"[^\"]*\"", "", attr)
            if not re.search(r"\balt\s*=", attr):
                attr += f' alt="{alt}"'
            chiusura = "/" if attr.rstrip().endswith("/") else ""
            attr = attr.rstrip().rstrip("/")
            return (f'<{tag}{attr} src="{grande}" srcset="{srcset}" sizes="(max-width: 800px) 100vw, 1600px" '
                    f'loading="lazy" decoding="async"{chiusura}>')
        stile = _attr(attr, "style") or ""
        stile = re.sub(r"background-image\s*:[^;]*;?", "", stile).strip()
        stile = (stile + "; " if stile and not stile.endswith(";") else stile) + \
            f"background-image:url('{grande}');background-size:cover;background-position:center"
        attr = re.sub(r"\sstyle\s*=\s*\"[^\"]*\"", "", attr) + f' style="{stile}"'
        return f"<{tag}{attr}>"

    return SPAZIO_RE.sub(sostituisci, html)


def applica(slug: str, solo_elenco: bool = False) -> dict:
    cart = BASE / "demo" / slug
    sorgente = cart / "personalizzata" / "modello.html"
    if not sorgente.exists():
        return {"errore": f"Manca {sorgente.relative_to(BASE)}: prima va creata la demo personalizzata."}
    html = sorgente.read_text(encoding="utf-8")
    lista = spazi(html)
    entrata = cart / "foto-da-inserire"
    entrata.mkdir(exist_ok=True)
    foto = sorted(p for p in entrata.iterdir()
                  if p.suffix.lower() in ESTENSIONI and ".convertita." not in p.name)
    file_scelte = cart / "foto.json"
    precedente = json.loads(file_scelte.read_text(encoding="utf-8")) if file_scelte.exists() else {}
    scelte = assegna(lista, foto, precedente)

    if solo_elenco:
        return {"spazi": [{**s, "foto": scelte.get(s["nome"], {}).get("file", "")} for s in lista],
                "foto_non_usate": [f.name for f in foto if f.name not in {v['file'] for v in scelte.values()}]}

    fatte, errori = [], []
    for s in lista:
        v = scelte.get(s["nome"])
        if not v:
            continue
        try:
            img = taglia(apri(entrata / v["file"]), s["rapporto"], v.get("fuoco", "auto"))
            misure = salva_misure(img, cart / "personalizzata" / "img", _chiave(s["nome"]))
            html = inserisci(html, s["nome"], misure, s["descrizione"] or s["nome"].replace("-", " "))
            fatte.append(s["nome"])
        except Exception as e:
            errori.append(f"{s['nome']} ({v['file']}): {e}")
    (cart / "personalizzata" / "index.html").write_text(html, encoding="utf-8")
    file_scelte.write_text(json.dumps(scelte, ensure_ascii=False, indent=1), encoding="utf-8")
    vuoti = [s["nome"] for s in lista if s["nome"] not in fatte]
    return {"inserite": fatte, "spazi_vuoti": vuoti, "errori": errori,
            "pagina": str((cart / "personalizzata" / "index.html").relative_to(BASE))}


def testo_per_jarvis(r: dict) -> str:
    if r.get("errore"):
        return r["errore"]
    if "spazi" in r:
        righe = [f"{s['nome']} ({s['formato']}): {s['foto'] or 'vuoto'}" for s in r["spazi"]]
        return "Spazi foto: " + "; ".join(righe) + ". Foto non usate: " + (", ".join(r["foto_non_usate"]) or "nessuna") + "."
    t = f"Foto inserite: {len(r['inserite'])}."
    if r["spazi_vuoti"]:
        t += " Spazi ancora vuoti: " + ", ".join(r["spazi_vuoti"]) + "."
    if r["errori"]:
        t += " Problemi: " + "; ".join(r["errori"]) + "."
    return t


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    risultato = applica(sys.argv[1], solo_elenco="--elenco" in sys.argv)
    print(testo_per_jarvis(risultato))
