"""Accesso all'account Google della Segreteria (Gmail + Drive)."""
import io
import os
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

CARTELLA = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/gmail.compose",
          "https://www.googleapis.com/auth/drive.file"]
NOME_CARTELLA_DRIVE = "Segreteria Jarvis"

def servizio(nome, versione):
    tok = os.path.join(CARTELLA, "token_segreteria.json")
    cred = Credentials.from_authorized_user_file(tok, SCOPES) if os.path.exists(tok) else None
    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            try:
                cred.refresh(Request())
            except RefreshError:
                # accesso scaduto o revocato (invalid_grant): si rifà il login nel browser
                print("Google: accesso scaduto, apro il browser per un nuovo accesso.")
                cred = None
        if not cred or not cred.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                os.path.join(CARTELLA, "credentials.json"), SCOPES)
            cred = flow.run_local_server(port=0)
        with open(tok, "w") as f:
            f.write(cred.to_json())
    return build(nome, versione, credentials=cred, cache_discovery=False)

def _cartella(drive):
    q = (f"name='{NOME_CARTELLA_DRIVE}' and "
         "mimeType='application/vnd.google-apps.folder' and trashed=false")
    trovate = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if trovate:
        return trovate[0]["id"]
    return drive.files().create(
        body={"name": NOME_CARTELLA_DRIVE, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]

def salva_su_drive(nome_file, testo):
    """Salva un file di testo nella cartella 'Segreteria Jarvis' del Drive."""
    try:
        drive = servizio("drive", "v3")
        media = MediaIoBaseUpload(io.BytesIO(testo.encode("utf-8")), mimetype="text/plain")
        drive.files().create(body={"name": nome_file, "parents": [_cartella(drive)]},
                             media_body=media, fields="id").execute()
    except Exception as e:
        print("Segreteria: Drive non raggiungibile:", e)


# ---------------------------------------------------------------- cartelle dei progetti
# Con il permesso "drive.file" Jarvis vede e tocca SOLO le cartelle e i file che crea lui.
# Non esiste nessuna funzione che cancella: gli agenti aggiungono file, non ne tolgono.

RADICE_DRIVE = "Jarvis"


def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _trova_o_crea(drive, nome, padre=None):
    q = f"name='{_q(nome)}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if padre:
        q += f" and '{padre}' in parents"
    trovate = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if trovate:
        return trovate[0]["id"]
    corpo = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    if padre:
        corpo["parents"] = [padre]
    return drive.files().create(body=corpo, fields="id").execute()["id"]


def _file_testo(drive, cartella_id, nome_file, testo, mimetype="text/plain", file_id=None):
    media = MediaIoBaseUpload(io.BytesIO(testo.encode("utf-8")), mimetype=mimetype)
    if file_id:
        drive.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    return drive.files().create(body={"name": nome_file, "parents": [cartella_id]},
                                media_body=media, fields="id").execute()["id"]


def crea_cartella_progetto(nome, sottocartelle, md_testo):
    """Crea Jarvis / Progetti / <nome> con le sottocartelle e il file progetto.md."""
    drive = servizio("drive", "v3")
    radice = _trova_o_crea(drive, RADICE_DRIVE)
    progetti = _trova_o_crea(drive, "Progetti", radice)
    cart = _trova_o_crea(drive, nome, progetti)
    sub = {s: _trova_o_crea(drive, s, cart) for s in sottocartelle}
    md_id = _file_testo(drive, cart, "progetto.md", md_testo, "text/markdown")
    link = drive.files().get(fileId=cart, fields="webViewLink").execute().get("webViewLink", "")
    return {"id": cart, "link": link, "sub": sub, "md_id": md_id}


def aggiorna_progetto_md(md_id, md_testo):
    drive = servizio("drive", "v3")
    _file_testo(drive, None, "progetto.md", md_testo, "text/markdown", file_id=md_id)


def aggiungi_file_progetto(cartella_id, nome_file, testo, mimetype="text/plain"):
    """Aggiunge un file nuovo nella sottocartella indicata (non sovrascrive mai niente)."""
    drive = servizio("drive", "v3")
    return _file_testo(drive, cartella_id, nome_file, testo, mimetype)


def crea_foglio(nome, testo_csv, cartella="Lead", caselle=None):
    """Crea un Foglio Google da un CSV in Jarvis / <cartella>. Restituisce il link. Non sovrascrive mai niente.
    caselle=(prima, dopo_ultima): righe (da 0) in cui la colonna A diventa una casella da spuntare."""
    drive = servizio("drive", "v3")
    cart = _trova_o_crea(drive, cartella, _trova_o_crea(drive, RADICE_DRIVE))
    media = MediaIoBaseUpload(io.BytesIO(testo_csv.encode("utf-8")), mimetype="text/csv")
    f = drive.files().create(body={"name": nome, "parents": [cart],
                                   "mimeType": "application/vnd.google-apps.spreadsheet"},
                             media_body=media, fields="id,webViewLink").execute()
    if caselle and caselle[1] > caselle[0]:
        try:
            fogli = servizio("sheets", "v4").spreadsheets()
            foglio_id = fogli.get(spreadsheetId=f["id"], fields="sheets.properties.sheetId").execute()[
                "sheets"][0]["properties"]["sheetId"]
            area = {"sheetId": foglio_id, "startRowIndex": caselle[0], "endRowIndex": caselle[1],
                    "startColumnIndex": 0, "endColumnIndex": 1}
            fogli.batchUpdate(spreadsheetId=f["id"], body={"requests": [
                {"setDataValidation": {"range": area, "rule": {"condition": {"type": "BOOLEAN"}}}}]}).execute()
        except Exception as e:
            print("Lead: caselle non aggiunte al foglio:", e)
    return f.get("webViewLink", "")


def condividi_con_link(file_id, ruolo="reader"):
    """Chiunque abbia il link può aprire la cartella (e tutto quello che c'è dentro) senza chiedere l'accesso.
    ruolo: reader (vede e scarica), commenter, writer (può anche aggiungere e modificare file)."""
    if ruolo not in ("reader", "commenter", "writer"):
        ruolo = "reader"
    drive = servizio("drive", "v3")
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": ruolo, "allowFileDiscovery": False},
                               fields="id").execute()
    return ruolo


def token_presente():
    return os.path.exists(os.path.join(CARTELLA, "token_segreteria.json"))
