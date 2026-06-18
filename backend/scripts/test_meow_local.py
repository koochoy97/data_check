"""Test local del scraper con MEOW en modo visible para diagnosticar select-control-button disabled."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import os
from app.scraper.reply_io import download_all_reports

async def main():
    result = await download_all_reports(
        email=os.environ["REPLY_IO_EMAIL"],
        password=os.environ["REPLY_IO_PASSWORD"],
        clients=[{"client_id": "mova", "client_name": "MOVA", "team_id": 479156, "download_dir": "/tmp/test_mova"}],
        on_progress=print,
        headless=False,
    )
    print("RESULT:", result)

asyncio.run(main())
