"""Chiede al modello una risposta in formato dati (JSON)."""
import json
import re
from .config import ANTHROPIC_API_KEY, MODELLO
try:
    import uso
except Exception:     # prova da sola, fuori da Jarvis
    uso = None

try:
    import ai                       # Claude + AI di riserva
    _client = ai.client(api_key=ANTHROPIC_API_KEY)
except ImportError:                 # prova da sola, fuori da Jarvis
    import anthropic
    _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def chiedi_json(istruzioni, testo):
    r = _client.messages.create(
        model=MODELLO, max_tokens=1000,
        system=istruzioni + "\nRispondi SOLO con JSON valido, senza altro testo.",
        messages=[{"role": "user", "content": testo}])
    if uso:
        uso.registra("segreteria", r)
    t = "".join(b.text for b in r.content if b.type == "text")
    t = re.sub(r"```(json)?", "", t).strip()
    return json.loads(t)
