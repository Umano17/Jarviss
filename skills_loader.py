"""
Jarvis – gestione delle skill.

Ogni skill è una cartella dentro skills/ (accanto a questo file) con un file SKILL.md:

    ---
    name: nome-skill
    description: quando usarla, in una frase
    metadata:
      categoria: Lavoro siti
      titolo: Nome da mostrare   # facoltativo, con accenti e maiuscole
      conferma: si        # "si" = Jarvis chiede conferma prima di eseguire azioni
    ---
    # istruzioni...

Jarvis attiva una skill con lo strumento skill_attiva (a voce) oppure dal widget Skill (un clic).
Le istruzioni della skill attiva vengono aggiunte al prompt di Jarvis finché non la disattivi.

Prova rapida dal Terminale:  python3 skills_loader.py
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

BASE = Path(__file__).parent
CARTELLA_SKILL = BASE / "skills"
FILE_STATO = BASE / "dati" / "skill_attiva.json"
MAX_ISTRUZIONI = 12000          # caratteri: oltre, il testo viene tagliato per non appesantire ogni richiesta

_FRONTMATTER = re.compile(r"^﻿?---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.S)
_NOME_VALIDO = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")


def _pulisci(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _leggi_frontmatter(testo: str) -> tuple[dict, str]:
    """Legge l'intestazione YAML semplice (anche il blocco metadata) senza librerie esterne."""
    m = _FRONTMATTER.match(testo)
    if not m:
        return {}, testo
    meta: dict = {}
    sezione = None
    for riga in m.group(1).splitlines():
        if not riga.strip() or riga.lstrip().startswith("#"):
            continue
        if riga[:1] in (" ", "\t") and sezione:
            k, _, v = riga.strip().partition(":")
            meta.setdefault(sezione, {})[k.strip()] = _pulisci(v.split(" #")[0])
            continue
        k, _, v = riga.partition(":")
        k, v = k.strip(), v.strip()
        if v:
            meta[k] = _pulisci(v)
            sezione = None
        else:
            sezione = k
    return meta, m.group(2)


def _si(v) -> bool:
    return str(v or "").strip().lower() in ("si", "sì", "true", "yes", "1")


class GestoreSkill:
    def __init__(self, cartella: Path = CARTELLA_SKILL, file_stato: Path = FILE_STATO):
        self.cartella = Path(cartella)
        self.file_stato = Path(file_stato)
        self._lock = threading.Lock()
        self.skills: dict[str, dict] = {}
        self.errori: list[str] = []
        self.attiva_nome: str | None = None
        self.ricarica()
        self._carica_stato()

    # ---------- lettura ----------
    def ricarica(self) -> None:
        """Rilegge la cartella: chiamala dopo aver aggiunto o modificato una skill."""
        trovate, errori = {}, []
        for f in sorted(self.cartella.glob("*/SKILL.md")):
            try:
                meta, corpo = _leggi_frontmatter(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as e:
                errori.append(f"{f.parent.name}: {e}")
                continue
            nome = str(meta.get("name") or f.parent.name).strip().lower()
            if not _NOME_VALIDO.match(nome):
                errori.append(f"{f.parent.name}: nome non valido '{nome}' (solo minuscole, numeri e trattini)")
                continue
            if nome in trovate:
                errori.append(f"{f.parent.name}: nome '{nome}' già usato da un'altra skill")
                continue
            extra = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
            trovate[nome] = {
                "nome": nome,
                "titolo": extra.get("titolo") or nome.replace("-", " ").capitalize(),
                "descrizione": str(meta.get("description", "")).strip(),
                "categoria": extra.get("categoria", "Altro") or "Altro",
                "conferma": _si(extra.get("conferma", "no")),
                "istruzioni": corpo.strip()[:MAX_ISTRUZIONI],
                "file": str(f),
            }
        with self._lock:
            self.skills = trovate
            self.errori = errori
            if self.attiva_nome not in self.skills:
                self.attiva_nome = None
        for e in errori:
            print("Skill ignorata ->", e)

    def elenco(self, categoria: str | None = None) -> list[dict]:
        """Elenco per il widget (senza il testo completo delle istruzioni)."""
        with self._lock:
            return [
                {k: s[k] for k in ("nome", "titolo", "descrizione", "categoria", "conferma")}
                | {"attiva": s["nome"] == self.attiva_nome}
                for s in self.skills.values()
                if not categoria or s["categoria"].lower() == categoria.lower()
            ]

    def stato(self, categoria: str | None = None) -> dict:
        return {"skills": self.elenco(categoria), "attiva": self.attiva_nome, "errori": list(self.errori)}

    def trova(self, nome: str) -> str | None:
        """Accetta anche 'Demo attività', 'demo_attivita' ecc. e restituisce il nome esatto."""
        n = str(nome or "").strip().lower()
        if n in self.skills:
            return n
        n = re.sub(r"[^a-z0-9]+", "-", n.replace("à", "a").replace("è", "e").replace("é", "e")
                   .replace("ì", "i").replace("ò", "o").replace("ù", "u")).strip("-")
        return n if n in self.skills else None

    # ---------- attivazione ----------
    def attiva(self, nome: str) -> dict:
        esatto = self.trova(nome)
        if not esatto:
            raise KeyError(f"Skill sconosciuta: {nome}")
        with self._lock:
            self.attiva_nome = esatto
        self._salva_stato()
        return self.skills[esatto]

    def disattiva(self) -> None:
        with self._lock:
            self.attiva_nome = None
        self._salva_stato()

    # ---------- testo per il modello ----------
    def contesto_per_modello(self) -> str:
        """Da aggiungere al prompt di sistema a ogni richiesta."""
        with self._lock:
            skills = list(self.skills.values())
            attiva = self.skills.get(self.attiva_nome) if self.attiva_nome else None
        if not skills:
            return ""
        righe = [f"- {s['nome']}: {s['descrizione']}" for s in skills]
        testo = (
            "SKILL\nHai delle skill: procedure scritte per compiti ricorrenti. Se la richiesta corrisponde "
            "chiaramente a una skill diversa da quella attiva, usa lo strumento skill_attiva e poi segui le "
            "istruzioni che ricevi. Quando il compito è finito o l'utente cambia argomento, usa skill_disattiva. "
            "Non leggere ad alta voce il nome tecnico della skill: di' solo cosa stai per fare.\n" + "\n".join(righe)
        )
        if attiva:
            testo += f"\n\nSKILL ATTIVA: {attiva['nome']}\nSegui queste istruzioni:\n{attiva['istruzioni']}"
            if attiva["conferma"]:
                testo += ("\n\nIMPORTANTE: prima di qualsiasi azione che modifica file, salva dati o tocca il "
                          "trader, chiedi conferma a voce all'utente e attendi un sì.")
        return testo

    # ---------- stato su disco ----------
    def _salva_stato(self) -> None:
        try:
            self.file_stato.parent.mkdir(parents=True, exist_ok=True)
            self.file_stato.write_text(json.dumps({"attiva": self.attiva_nome}), encoding="utf-8")
        except OSError as e:
            print("Non riesco a salvare la skill attiva:", e)

    def _carica_stato(self) -> None:
        try:
            nome = json.loads(self.file_stato.read_text(encoding="utf-8")).get("attiva")
            if nome in self.skills:
                self.attiva_nome = nome
        except (OSError, ValueError, AttributeError):
            pass


gestore = GestoreSkill()

if __name__ == "__main__":
    for s in gestore.elenco():
        print(f"[{s['categoria']}] {s['nome']}: {s['descrizione'][:70]}...")
    print(f"\nTotale: {len(gestore.skills)} skill" + (f", {len(gestore.errori)} con errori" if gestore.errori else ""))
