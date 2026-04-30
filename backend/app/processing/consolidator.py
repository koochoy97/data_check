"""Consolida los CSVs de People y Email Activity de varios clientes en dos archivos."""
from datetime import date
from pathlib import Path

import pandas as pd


def consolidate(
    per_client_files: list[dict],
    output_dir: Path,
    run_date: date | None = None,
) -> dict[str, Path]:
    """
    Args:
        per_client_files: lista de dicts con keys:
            - client_id (str)
            - client_name (str)
            - people_csv (Path | None)
            - email_csv (Path | None)
        output_dir: carpeta donde escribir los consolidados.
        run_date: fecha para el sufijo del archivo. Default = hoy.

    Returns: {"people": Path, "email_activity": Path} (sólo claves con datos).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    run_date = run_date or date.today()
    suffix = run_date.isoformat()

    people_frames = []
    email_frames = []

    for entry in per_client_files:
        cid = entry["client_id"]
        cname = entry["client_name"]

        people_csv = entry.get("people_csv")
        if people_csv and Path(people_csv).exists():
            df = pd.read_csv(people_csv)
            df.insert(0, "client_id", cid)
            df.insert(1, "client_name", cname)
            people_frames.append(df)

        email_csv = entry.get("email_csv")
        if email_csv and Path(email_csv).exists():
            df = pd.read_csv(email_csv)
            df.insert(0, "client_id", cid)
            df.insert(1, "client_name", cname)
            email_frames.append(df)

    result: dict[str, Path] = {}

    if people_frames:
        people_out = output_dir / f"people_consolidated_{suffix}.csv"
        pd.concat(people_frames, ignore_index=True, sort=False).to_csv(people_out, index=False)
        result["people"] = people_out

    if email_frames:
        email_out = output_dir / f"email_activity_consolidated_{suffix}.csv"
        pd.concat(email_frames, ignore_index=True, sort=False).to_csv(email_out, index=False)
        result["email_activity"] = email_out

    return result
