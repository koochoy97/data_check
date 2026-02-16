"""
Sheet Builder: creates a single Google Spreadsheet for a client
and orchestrates both processing modules to populate it.
"""
from datetime import datetime


def crear_spreadsheet(nombre_cliente: str, gc, drive_service):
    """
    Creates a new spreadsheet with unique name.
    Returns the gspread Spreadsheet object.
    """
    base_name = f"Validacion - {nombre_cliente} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    final_name = base_name
    i = 1

    while True:
        r = drive_service.files().list(
            q=f"name='{final_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            fields="files(id)",
        ).execute()
        if not r["files"]:
            break
        final_name = f"{base_name} ({i})"
        i += 1

    spreadsheet = gc.create(final_name)

    # Remove default Sheet1
    default_sheet = spreadsheet.sheet1
    # We'll rename it instead of deleting (can't delete last sheet)
    default_sheet.update_title("_temp")

    return spreadsheet
