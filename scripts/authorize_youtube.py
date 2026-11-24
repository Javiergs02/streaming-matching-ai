#!/usr/bin/env python3
"""
Script de Autorización OAuth 2.0 para YouTube Analytics API.
Permite vincular una cuenta corporativa de Google para generar un nuevo
archivo credentials_token.json con refresh_token permanente.
"""

import os
import sys
import json
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import webbrowser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "451916252266-05fume67cv0qi7pqjgi97nkvrfe5o1es.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Fallback: intentar leer desde youtube_credentials.json si existe
if not CLIENT_SECRET:
    _creds_json = Path(__file__).resolve().parent.parent / "infrastructure" / "credentials" / "youtube_credentials.json"
    if _creds_json.exists():
        try:
            with open(_creds_json, "r", encoding="utf-8") as _f:
                _cdata = json.load(_f)
                _info = _cdata.get("installed") or _cdata.get("web") or {}
                CLIENT_SECRET = _info.get("client_secret", "")
                if not CLIENT_ID or CLIENT_ID.startswith("451916"):
                    CLIENT_ID = _info.get("client_id", CLIENT_ID)
        except Exception:
            pass

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    "https://www.googleapis.com/auth/youtube.readonly"
]
REDIRECT_PORT = int(os.getenv("OAUTH_REDIRECT_PORT", "8080"))
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"

auth_code_received = None
server_done = threading.Event()

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code_received
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code_received = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html_success = """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #2e7d32;">✅ ¡Autorización completada con éxito!</h1>
                <p>Las credenciales de YouTube se han guardado correctamente en el sistema.</p>
                <p>Ya puedes cerrar esta pestaña del navegador y volver a tu terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(html_success.encode("utf-8"))
        elif "error" in params:
            error = params.get("error", ["desconocido"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h1>Error de autorización: {error}</h1>".encode("utf-8"))

        server_done.set()

    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor HTTP

def exchange_code_for_token(code: str) -> dict:
    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    root_dir = Path(__file__).resolve().parent.parent
    creds_output = root_dir / "infrastructure" / "credentials" / "youtube_credentials.json"
    creds_output.parent.mkdir(parents=True, exist_ok=True)

    auth_params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent"
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(auth_params)}"

    print("\n" + "=" * 65)
    print("🔐 AUTORIZACIÓN OAUTH 2.0 - YOUTUBE ANALYTICS API")
    print("=" * 65)
    print("1. Abre el siguiente enlace en tu navegador con la cuenta de Amuse:")
    print(f"\n👉 {auth_url}\n")
    print("2. Inicia sesión con la cuenta corporativa autorizada.")
    print("3. Haz clic en 'Permitir' para otorgar permisos de lectura de estadísticas.")
    print("=" * 65)

    # Intentar abrir el navegador automáticamente
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    manual_code = []
    def wait_for_manual_input():
        try:
            val = input("\n👉 Si otra persona hace la autorización, pega aquí la URL resultante o el código:\n> ").strip()
            if val:
                manual_code.append(val)
                server_done.set()
        except Exception:
            pass

    input_thread = threading.Thread(target=wait_for_manual_input, daemon=True)
    input_thread.start()

    # Iniciar servidor local para capturar el callback
    server = None
    try:
        server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"\n⏳ Esperando respuesta en segundo plano...")
        print("  - Si lo abres en ESTE mismo PC, se capturará solo.")
        print("  - Si se lo envías a tu JEFE, pídele que te pase la URL a la que le redirija y pégala aquí abajo.")
        
        while not server_done.is_set():
            server_done.wait(timeout=0.5)
    except KeyboardInterrupt:
        print("\nOperación cancelada por el usuario.")
        sys.exit(1)
    finally:
        if server:
            server.shutdown()
            server.server_close()

    code = auth_code_received
    if not code and manual_code:
        code_input = manual_code[0]
        if code_input.startswith("http"):
            parsed = urllib.parse.urlparse(code_input)
            code = urllib.parse.parse_qs(parsed.query).get("code", [code_input])[0]
        else:
            code = code_input

    if not code:
        print("❌ No se recibió ningún código. Proceso abortado.")
        sys.exit(1)

    print("\n🔄 Intercambiando código con Google por tokens de acceso permanente...")
    try:
        tokens = exchange_code_for_token(code)
    except Exception as e:
        print(f"❌ Error al intercambiar tokens con Google: {e}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("⚠️ Advertencia: Google no devolvió 'refresh_token'. Asegúrate de que usaste 'prompt=consent'.")

    final_creds = {
        "token": tokens.get("access_token"),
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scopes": SCOPES,
        "universe_domain": "googleapis.com",
        "account": "",
        "expiry": ""
    }

    with open(creds_output, "w", encoding="utf-8") as f:
        json.dump(final_creds, f, indent=2)

    print("\n" + "=" * 65)
    print("🎉 ¡CREDENCIALES GUARDADAS CON ÉXITO!")
    print(f"📁 Archivo: {creds_output}")
    print("=" * 65)
    print("Ya puedes ejecutar la ingesta de YouTube:")
    print("  venv/bin/python apps/event_manager/src/run_yt_monthly_territory_events.py --start-date 2026-09-01\n")

if __name__ == "__main__":
    main()

