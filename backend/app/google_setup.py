"""One-time setup: run this to authorize Google OAuth.
Usage: cd backend && python -m app.google_setup
"""
import sys
import os

# Ensure we can find app module and load .env from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', '.env'))

from app.google_auth import authorize_interactive

if __name__ == "__main__":
    print("Abriendo navegador para autorizar Google Sheets + Drive...")
    print("Si el navegador no se abre, copia la URL que aparece abajo.")
    print()
    authorize_interactive()
    print("\nListo! Ya puedes correr la app.")
