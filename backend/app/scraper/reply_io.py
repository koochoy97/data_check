"""Playwright scraper for Reply.io - downloads People CSV + Email Activity CSV"""
import asyncio
import random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# Required for running Chromium inside Docker (avoids /dev/shm crashes)
CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-setuid-sandbox",
]


class WorkspaceUnavailable(Exception):
    """El workspace de Reply.io no es accesible para la sesión actual.

    Se levanta cuando `SwitchTeam` devuelve no-2xx (workspace eliminado o bot
    desinvitado) o cuando la verificación post-switch detecta que el workspace
    activo no coincide con el esperado. Es una falla persistente: no se reintenta.
    """


async def _switch_workspace(
    page,
    team_id: int,
    emit,
    alert_context: dict | None = None,
) -> None:
    """Cambia al workspace `team_id` y valida que el switch fue efectivo.

    Levanta `WorkspaceUnavailable` si:
      - Capa 1: la response del SwitchTeam es ausente o no-2xx (típicamente 403
        cuando el bot no es miembro del workspace).
      - Capa 2: tras el switch, `/Team/GetTeamData` devuelve un teamId distinto
        al esperado.

    Si `alert_context` es un dict con `client_name`/`siete_id`/`team_id`, al
    detectarse la falla se emite una alerta a Slack (best-effort, no aborta).
    """
    url = f"https://run.reply.io/Home/SwitchTeam?teamId={team_id}"

    # ── Capa 1: validar status code del SwitchTeam ────────────────────────────
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    if resp is None:
        reason = "SwitchTeam: no se obtuvo response del servidor"
        _emit_workspace_alert(alert_context, reason, emit)
        raise WorkspaceUnavailable(f"teamId={team_id}: {reason}")

    if not resp.ok:
        body_preview = ""
        try:
            body_preview = (await resp.text())[:200]
        except Exception:
            pass
        reason = f"SwitchTeam HTTP {resp.status}: {body_preview}".strip()
        _emit_workspace_alert(alert_context, reason, emit)
        raise WorkspaceUnavailable(f"teamId={team_id}: {reason}")

    # ── Capa 2: validar workspace activo vía /Team/GetTeamData ────────────────
    await asyncio.sleep(3)  # gracia para que la sesión se asiente server-side

    try:
        active = await page.evaluate(
            """async () => {
                try {
                    const r = await fetch('/Team/GetTeamData', {credentials: 'include'});
                    if (!r.ok) return {__error: 'http_' + r.status};
                    return await r.json();
                } catch (e) {
                    return {__error: String(e)};
                }
            }"""
        )
    except Exception as e:
        emit(f"[switch] WARN: no pude consultar /Team/GetTeamData ({e}); confío en Capa 1")
        await asyncio.sleep(5)
        return

    if not isinstance(active, dict) or "__error" in active:
        err = active.get("__error", "respuesta no es dict") if isinstance(active, dict) else "respuesta no es dict"
        emit(f"[switch] WARN: /Team/GetTeamData no disponible ({err}); confío en Capa 1")
        await asyncio.sleep(5)
        return

    observed_raw = (
        active.get("teamId")
        or active.get("id")
        or active.get("currentTeamId")
    )
    if observed_raw is None:
        emit(f"[switch] WARN: /Team/GetTeamData no devolvió teamId/id/currentTeamId; confío en Capa 1")
        await asyncio.sleep(5)
        return

    try:
        observed = int(observed_raw)
    except (TypeError, ValueError):
        emit(f"[switch] WARN: teamId observado no es int ({observed_raw!r}); confío en Capa 1")
        await asyncio.sleep(5)
        return

    if observed != int(team_id):
        reason = (
            f"workspace activo no coincide: esperado teamId={team_id}, "
            f"sesión activa en teamId={observed}"
        )
        _emit_workspace_alert(alert_context, reason, emit)
        raise WorkspaceUnavailable(f"teamId={team_id}: {reason}")

    await asyncio.sleep(5)  # tiempo de gracia que ya teníamos antes del flujo


def _emit_workspace_alert(alert_context: dict | None, reason: str, emit) -> None:
    """Best-effort: dispara alerta Slack si hay contexto. Nunca propaga errores."""
    if not alert_context:
        return
    try:
        from app.processing.send_slack import send_workspace_unavailable_alert
        send_workspace_unavailable_alert(
            client_name=alert_context.get("client_name") or alert_context.get("client_id") or "?",
            siete_id=alert_context.get("siete_id"),
            team_id=alert_context.get("team_id"),
            reason=reason,
        )
    except Exception as e:
        emit(f"[switch] WARN: no se pudo emitir alerta Slack: {e}")


async def _retry(coro_fn, max_attempts=3, base_delay=5, emit=None, label="operación"):
    """Retry an async operation with exponential backoff + jitter."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn()
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 3)
                msg = f"[retry] {label} falló (intento {attempt}/{max_attempts}): {e}. Reintentando en {delay:.0f}s..."
                if emit:
                    emit(msg)
                else:
                    print(msg)
                await asyncio.sleep(delay)
            else:
                msg = f"[retry] {label} falló después de {max_attempts} intentos: {e}"
                if emit:
                    emit(msg)
                else:
                    print(msg)
    raise last_error


async def fetch_workspaces(
    email: str,
    password: str,
    headless: bool = True,
) -> list[dict]:
    """
    Logs into Reply.io and scrapes all available workspaces.
    Intercepts the /api/v2/users/teams API call that Reply.io makes internally.
    Returns: [{"team_id": 123, "name": "Workspace Name"}, ...]
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=CHROMIUM_ARGS)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # Intercept API calls to capture team/workspace data
        captured_teams = []

        async def handle_response(response):
            url = response.url.lower()
            if "/team" in url or "/workspace" in url or "/account" in url:
                try:
                    body = await response.json()
                    print(f"[fetch_workspaces] Intercepted {response.url}: {str(body)[:200]}")
                    if isinstance(body, list):
                        for item in body:
                            if isinstance(item, dict) and ("id" in item or "teamId" in item):
                                tid = item.get("id") or item.get("teamId")
                                name = item.get("name") or item.get("teamName") or item.get("title") or ""
                                if tid:
                                    captured_teams.append({"team_id": int(tid), "name": name})
                    elif isinstance(body, dict):
                        # Could be nested: body.teams, body.data, etc.
                        for key in ("teams", "data", "items", "results"):
                            if key in body and isinstance(body[key], list):
                                for item in body[key]:
                                    if isinstance(item, dict):
                                        tid = item.get("id") or item.get("teamId")
                                        name = item.get("name") or item.get("teamName") or item.get("title") or ""
                                        if tid:
                                            captured_teams.append({"team_id": int(tid), "name": name})
                except Exception:
                    pass

        page.on("response", handle_response)

        # LOGIN
        await page.goto("https://run.reply.io/", wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)

        if "oauth" in page.url or "login" in page.url.lower():
            await page.locator("input:visible").first.fill(email)
            await page.locator('input[type="password"]:visible').fill(password)
            await page.get_by_role("button", name="Sign in").click()
            try:
                await page.wait_for_url("**/run.reply.io/**", timeout=20_000)
            except Exception:
                pass
        await asyncio.sleep(5)

        # If intercepted teams from login/dashboard load, use those
        if captured_teams:
            print(f"[fetch_workspaces] Capturados {len(captured_teams)} teams de API interceptada")
            await browser.close()
            return captured_teams

        # Strategy 2: Try to find and click the workspace/account switcher in the UI
        print("[fetch_workspaces] No se interceptaron teams, buscando switcher en UI...")

        # Look for common workspace switcher patterns
        switcher_selectors = [
            '[data-test-id*="team"]',
            '[data-test-id*="workspace"]',
            '[class*="team-switch"]',
            '[class*="workspace"]',
            '[class*="account-switch"]',
        ]

        for sel in switcher_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    print(f"[fetch_workspaces] Encontrado switcher: {sel}")
                    await el.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        # Wait for any API calls triggered by opening the switcher
        await asyncio.sleep(3)

        if captured_teams:
            print(f"[fetch_workspaces] Capturados {len(captured_teams)} teams después de abrir switcher")
            await browser.close()
            return captured_teams

        # Strategy 3: Extract from page HTML (SwitchTeam links, etc.)
        print("[fetch_workspaces] Buscando links SwitchTeam en el HTML...")
        workspaces = await page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="SwitchTeam"], a[href*="switchTeam"], a[href*="team"]');
            for (const link of links) {
                const match = link.href.match(/teamId=(\\d+)/i);
                if (match) {
                    results.push({
                        team_id: parseInt(match[1]),
                        name: link.textContent.trim()
                    });
                }
            }
            return results;
        }""")

        if workspaces:
            print(f"[fetch_workspaces] Encontrados {len(workspaces)} workspaces en HTML")
            await browser.close()
            return workspaces

        # Strategy 4: Navigate to settings/team page
        print("[fetch_workspaces] Intentando Settings > Team...")
        await page.goto("https://run.reply.io/Dashboard/Material#/settings/team",
                       wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(5)

        if captured_teams:
            print(f"[fetch_workspaces] Capturados {len(captured_teams)} teams desde settings")
            await browser.close()
            return captured_teams

        # Debug: log what we see
        page_url = page.url
        page_title = await page.title()
        print(f"[fetch_workspaces] FALLO - URL: {page_url}, Title: {page_title}")
        print(f"[fetch_workspaces] captured_teams: {captured_teams}")

        await browser.close()
        return []


# Reciclar las páginas cada N clientes para evitar acumulación de memoria en Chromium
PAGE_RECYCLE_INTERVAL = 10


async def _login_reply_io(page, email: str, password: str, emit) -> None:
    """Realiza login en Reply.io en la página dada."""
    emit("Iniciando sesión en Reply.io...")
    await page.goto("https://run.reply.io/", wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(3)

    if "oauth" in page.url or "login" in page.url.lower():
        await page.locator("input:visible").first.fill(email)
        await page.locator('input[type="password"]:visible').fill(password)
        await page.get_by_role("button", name="Sign in").click()
        try:
            await page.wait_for_url("**/run.reply.io/**", timeout=20_000)
        except Exception:
            pass
    await asyncio.sleep(3)


async def download_all_reports(
    email: str,
    password: str,
    clients: list[dict],
    on_progress=None,
    headless: bool = True,
) -> dict[str, dict]:
    """
    Single login, iterates through all clients reusing the same browser session.
    Pages are recycled every PAGE_RECYCLE_INTERVAL clients to prevent memory leaks.
    The browser context (cookies/session) is preserved across recycles.

    Returns:
        {client_id: {"personas": Path, "correos": Path}} for successes,
        {client_id: {"error": str}} for failures.
    """

    def emit(msg: str):
        # If a callback is provided, defer printing to the caller (avoids duplicate log lines
        # when the wrapper also prefixes/echoes). Otherwise print directly.
        if on_progress:
            on_progress(msg)
        else:
            print(msg)

    results: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=CHROMIUM_ARGS)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
        )
        page = await context.new_page()
        page2 = await context.new_page()

        # ── LOGIN ONCE ──
        await _login_reply_io(page, email, password, emit)
        emit(f"Sesión iniciada. Procesando {len(clients)} clientes...")

        async def recycle_pages(reason: str):
            """Cierra y recrea las páginas (mantiene cookies del context)."""
            nonlocal page, page2
            emit(f"[recycle] Reciclando páginas ({reason})...")
            for p_obj in (page, page2):
                try:
                    await p_obj.close()
                except Exception:
                    pass
            page = await context.new_page()
            page2 = await context.new_page()
            await asyncio.sleep(2)

        # ── LOOP CLIENTS ──
        for idx, client in enumerate(clients, 1):
            cid = client["client_id"]
            team_id = client["team_id"]
            download_dir = Path(client["download_dir"])
            download_dir.mkdir(parents=True, exist_ok=True)

            alert_context = {
                "client_id": cid,
                "client_name": client.get("client_name") or cid,
                "siete_id": client.get("siete_id"),
                "team_id": team_id,
            }

            def emit_client(msg, _cid=cid, _idx=idx):
                emit(f"[{_idx}/{len(clients)}] {_cid}: {msg}")

            # Reciclar proactivamente cada N clientes
            if idx > 1 and (idx - 1) % PAGE_RECYCLE_INTERVAL == 0:
                await recycle_pages(f"cada {PAGE_RECYCLE_INTERVAL} clientes")

            # Reintentar el cliente entero hasta 2 veces si crashea la página
            client_attempts = 0
            max_client_attempts = 2
            while client_attempts < max_client_attempts:
                client_attempts += 1
                try:
                    emit_client(f"Cambiando a workspace {team_id}...")
                    await _switch_workspace(page, team_id, emit_client, alert_context=alert_context)

                    emit_client("Disparando export de Personas...")
                    people_direct = await _retry(
                        lambda: _trigger_people_export(page, download_dir, emit_client),
                        max_attempts=3, base_delay=5, emit=emit_client, label="trigger People export",
                    )

                    emit_client("Disparando export de Correos...")
                    await _retry(
                        lambda: _trigger_email_export(page2, emit_client),
                        max_attempts=3, base_delay=5, emit=emit_client, label="trigger Email export",
                    )

                    need_people = people_direct is None
                    emit_client(f"Esperando descargas (people={need_people}, correos=True)...")
                    people_notif, email_csv = await _poll_both_downloads(
                        page, page2, download_dir, emit_client, need_people=need_people,
                    )

                    people_csv = people_direct or people_notif
                    results[cid] = {"personas": people_csv, "correos": email_csv}
                    emit_client("OK")
                    break

                except WorkspaceUnavailable as e:
                    # Falla persistente del workspace (403, mismatch). No reintentar:
                    # el siguiente cliente arranca con su propio switch limpio.
                    emit_client(f"SKIP: {e}")
                    results[cid] = {"error": str(e)}
                    break

                except Exception as e:
                    err_str = str(e)
                    is_crash = "Page crashed" in err_str or "Target closed" in err_str or "Target page" in err_str

                    if is_crash and client_attempts < max_client_attempts:
                        emit_client(f"Página crasheada, reciclando y reintentando: {err_str[:100]}")
                        try:
                            await recycle_pages("crash recovery")
                        except Exception as recycle_err:
                            emit_client(f"Falló recycle, reiniciando login: {recycle_err}")
                            try:
                                await _login_reply_io(page, email, password, emit_client)
                            except Exception:
                                pass
                        continue

                    import traceback
                    traceback.print_exc()
                    emit_client(f"ERROR: {err_str[:200]}")
                    results[cid] = {"error": err_str}
                    break

        try:
            await page2.close()
        except Exception:
            pass
        await browser.close()

    return results


async def download_reports(
    email: str,
    password: str,
    team_id: int,
    download_dir: Path,
    on_progress=None,
    headless: bool = True,
) -> dict[str, Path]:
    """
    Downloads 2 CSVs from Reply.io in parallel:
    1. People CSV (All fields) - via People > Select All > More > Export to CSV > All fields
    2. Email Activity CSV - via Reports/Emails > Filter Last Year > Export contact CSV

    Both are async exports via notification center. We trigger both on separate tabs,
    then poll notifications for both download links simultaneously.

    Returns: {"personas": Path, "correos": Path}
    """

    def emit(msg: str):
        if on_progress:
            on_progress(msg)
        else:
            print(msg)

    download_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=200 if not headless else 0, args=CHROMIUM_ARGS)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
        )
        page = await context.new_page()

        # ── LOGIN ──
        emit("Iniciando sesión en Reply.io...")
        await page.goto("https://run.reply.io/", wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)

        if "oauth" in page.url or "login" in page.url.lower():
            await page.locator("input:visible").first.fill(email)
            await page.locator('input[type="password"]:visible').fill(password)
            await page.get_by_role("button", name="Sign in").click()
            try:
                await page.wait_for_url("**/run.reply.io/**", timeout=20_000)
            except Exception:
                pass
        await asyncio.sleep(3)

        # ── SWITCH WORKSPACE ──
        emit(f"Cambiando a workspace {team_id}...")
        await _switch_workspace(page, team_id, emit, alert_context=None)

        # ── TRIGGER BOTH EXPORTS (parallel on two tabs) ──
        page2 = await context.new_page()

        emit("Disparando export de Personas (All fields)...")
        people_direct = await _retry(
            lambda: _trigger_people_export(page, download_dir, emit),
            max_attempts=3, base_delay=5, emit=emit, label="trigger People export",
        )

        emit("Disparando export de Correos (contact CSV)...")
        await _retry(
            lambda: _trigger_email_export(page2, emit),
            max_attempts=3, base_delay=5, emit=emit, label="trigger Email export",
        )

        if people_direct:
            emit(f"People CSV descargado directamente ({people_direct.stat().st_size:,} bytes)")

        # ── POLL NOTIFICATIONS FOR REMAINING DOWNLOADS ──
        need_people = people_direct is None
        emit(f"Esperando descargas en notificaciones (people={need_people}, correos=True)...")
        people_notif, email_csv = await _poll_both_downloads(
            page, page2, download_dir, emit, need_people=need_people,
        )

        people_csv = people_direct or people_notif

        await page2.close()
        await browser.close()

        return {"personas": people_csv, "correos": email_csv}


async def _trigger_people_export(page, download_dir: Path, emit) -> Path | None:
    """Navigate to People, select all, trigger All fields export.
    Returns Path if direct download happened, None if async (notification)."""
    await page.goto(
        "https://run.reply.io/Dashboard/Material#/people/list",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await asyncio.sleep(5)

    # Click "All" tab — retry because Reply UI is slow to render
    for _ in range(3):
        try:
            await page.locator('text=/^All\\s*\\(/').first.click(timeout=10_000)
            break
        except Exception:
            await asyncio.sleep(2)
    await asyncio.sleep(2)

    # Select all in list
    for _ in range(3):
        try:
            await page.locator('[data-test-id="select-control-button"]').click(timeout=10_000)
            break
        except Exception:
            await asyncio.sleep(2)
    await asyncio.sleep(1)

    await page.locator("text=All in list").first.click(timeout=10_000)
    await asyncio.sleep(2)

    # More > Export to CSV > All fields
    await page.locator('button:has-text("More"):visible').first.click(timeout=10_000)
    await asyncio.sleep(1)
    await page.locator("text=Export to CSV").hover(timeout=10_000)
    await asyncio.sleep(1)

    # Try to catch direct download (some workspaces download immediately)
    try:
        async with page.expect_download(timeout=10_000) as download_info:
            await page.locator("text=/^All fields$/").first.click(timeout=5_000)
        download = await download_info.value
        dest = download_dir / "people.csv"
        await download.save_as(str(dest))
        emit("Export de Personas: descarga directa")
        return dest
    except Exception:
        # No direct download — it went to notification center (async)
        emit("Export de Personas disparado (async, esperando notificación)")
        return None


async def _trigger_email_export(page, emit):
    """Navigate to Reports/Emails, set filters, trigger export."""
    await page.goto(
        "https://run.reply.io/Dashboard/Material#/reports/emails",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await asyncio.sleep(5)

    # Open Filters > Date > Last Year > Apply (with retries on each step)
    for _ in range(3):
        try:
            await page.locator('[data-test-id="filters-drawer-toggle-button"]').click(timeout=10_000)
            break
        except Exception:
            await asyncio.sleep(2)
    await asyncio.sleep(2)  # extra time for drawer animation on heavy workspaces

    # Wait for the Date filter to be visible (heavy workspaces can take >10s to render),
    # then scroll it into view before clicking. Avoids "element is not visible" timeouts
    # on workspaces with many filters where Date is initially off-screen.
    date_loc = page.locator("text=Date").first
    try:
        await date_loc.wait_for(state="visible", timeout=30_000)
        await date_loc.scroll_into_view_if_needed(timeout=5_000)
    except Exception:
        # If wait/scroll fails, fall through to a regular click and let _retry handle it
        pass
    await date_loc.click(timeout=30_000)
    await asyncio.sleep(1)

    last_year_loc = page.locator("text=Last Year").first
    try:
        await last_year_loc.wait_for(state="visible", timeout=15_000)
        await last_year_loc.scroll_into_view_if_needed(timeout=5_000)
    except Exception:
        pass
    await last_year_loc.click(timeout=15_000)
    await asyncio.sleep(1)
    await page.locator('button:has-text("Apply")').click(timeout=10_000)
    await asyncio.sleep(5)

    # Close Filters
    await page.locator('[data-test-id="filters-drawer-toggle-button"]').click(timeout=10_000)
    await asyncio.sleep(1)

    # Trigger export
    await page.locator('button:has-text("Export"):visible').first.click(timeout=10_000)
    await asyncio.sleep(1)
    await page.locator("text=Export contact CSV").click(timeout=10_000)
    await asyncio.sleep(0.5)

    export_btn = page.locator('.MuiPopover-paper button:has-text("Export"), .MuiPaper-root button:has-text("Export")')
    if await export_btn.count() > 0:
        await export_btn.first.click()
    else:
        await page.locator('button:has-text("Export"):visible').last.click()

    await asyncio.sleep(2)
    emit("Export de Correos disparado")


async def _open_notification_panel(page):
    """Open the notification panel using multiple strategies."""
    # Strategy 1: Look for bell icon by common selectors
    bell_selectors = [
        '[data-test-id="notification-bell"]',
        '[aria-label*="otification"]',
        'svg[data-testid*="bell"]',
        'svg[data-testid*="notification"]',
    ]
    for sel in bell_selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click(timeout=3000)
                return True
        except Exception:
            continue

    # Strategy 2: Find the bell by its position (top-right area, usually an SVG or icon)
    # The bell is typically in the top nav bar, near the right side
    try:
        # Look for any clickable element in the notification area that contains a badge or SVG
        notif_area = page.locator('header >> svg, nav >> svg, [class*="notification"], [class*="bell"]').first
        if await notif_area.count() > 0:
            await notif_area.click(timeout=3000)
            return True
    except Exception:
        pass

    # Strategy 3: Click by coordinates (top-right area where bell typically is)
    try:
        await page.mouse.click(1870, 30)
        return True
    except Exception:
        return False


async def _poll_both_downloads(
    page, page2, download_dir: Path, emit,
    need_people: bool = True,
    max_wait: int = 600, poll_interval: int = 5, max_retries: int = 5,
) -> tuple[Path | None, Path]:
    """
    Poll notification center for People and/or Email Activity downloads.

    Uses Playwright locators directly to find and click download links
    in the notification panel.

    Returns: (people_csv_path_or_None, email_activity_csv_path)
    """
    people_csv = None
    email_csv = None
    people_retries = 0
    email_retries = 0
    consecutive_empty_polls = 0
    start = datetime.now()
    poll = 0

    while (datetime.now() - start).total_seconds() < max_wait:
        if (people_csv or not need_people) and email_csv:
            break

        poll += 1
        current_interval = min(poll_interval + (poll // 10) * 2, 15)

        # Open notification panel
        await _open_notification_panel(page)
        await asyncio.sleep(2)

        elapsed = int((datetime.now() - start).total_seconds())

        # ── Check for People CSV notification ──
        if need_people and not people_csv:
            try:
                # "Contacts export completed. Download." — click the "Download" link
                people_link = page.locator('text=Contacts export completed').locator('..').locator('..').locator('a:visible').first
                if await people_link.count() == 0:
                    # Try broader: any link near "export completed"
                    people_link = page.locator('a:has-text("Download"):visible').first
                if await people_link.count() > 0:
                    emit(f"Descarga de Personas lista! ({elapsed}s)")
                    try:
                        people_csv = await _click_download_link(page, people_link, download_dir / "people.csv", emit)
                    except Exception as e:
                        emit(f"Error descargando People CSV: {e}")
            except Exception:
                pass

            # Check for failure
            try:
                failed = page.locator('text=Failed to export contacts').first
                if await failed.count() > 0 and not people_csv:
                    people_retries += 1
                    if people_retries <= max_retries:
                        delay = 5 * (2 ** (people_retries - 1)) + random.uniform(0, 5)
                        emit(f"Export de Personas falló, reintentando ({people_retries}/{max_retries}) en {delay:.0f}s...")
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(delay)
                        try:
                            await _trigger_people_export(page, download_dir, emit)
                        except Exception as e:
                            emit(f"Error re-disparando People export: {e}")
                        continue
                    else:
                        emit(f"Export de Personas falló {max_retries} veces, continuando sin People CSV")
                        need_people = False
            except Exception:
                pass

        # ── Check for Email Activity CSV notification ──
        if not email_csv:
            try:
                # "Download your contact-specific stats here." — click "here" link
                email_link = page.locator('text=contact-specific stats').locator('..').locator('a:visible').first
                if await email_link.count() == 0:
                    email_link = page.locator('a:has-text("here"):near(:text("contact-specific stats"))').first
                if await email_link.count() == 0:
                    # Broader: look for "here" link that's visible in the notification area
                    email_link = page.locator('text=contact-specific stats').locator('..').locator('..').locator('a:visible').first
                if await email_link.count() > 0:
                    emit(f"Descarga de Correos lista! ({elapsed}s)")
                    try:
                        email_csv = await _click_download_link(page, email_link, download_dir / "email_activity.csv", emit)
                    except Exception as e:
                        emit(f"Error descargando Email CSV: {e}")
            except Exception:
                pass

            # Check for email failure
            try:
                failed_email = page.locator('text=/Failed to export(?!.*contacts)/').first
                if await failed_email.count() > 0 and not email_csv:
                    email_retries += 1
                    if email_retries <= max_retries:
                        delay = 5 * (2 ** (email_retries - 1)) + random.uniform(0, 5)
                        emit(f"Export de Correos falló, reintentando ({email_retries}/{max_retries}) en {delay:.0f}s...")
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(delay)
                        try:
                            await _trigger_email_export(page2, emit)
                        except Exception as e:
                            emit(f"Error re-disparando Email export: {e}")
                        continue
                    else:
                        emit(f"Export de Correos falló {max_retries} veces")
            except Exception:
                pass

        # Track empty polls
        if not people_csv and not email_csv:
            consecutive_empty_polls += 1
        else:
            consecutive_empty_polls = 0

        if (people_csv or not need_people) and email_csv:
            break

        # Status update every ~30s
        if poll % 6 == 0:
            pending = []
            if need_people and not people_csv:
                pending.append(f"Personas (retries: {people_retries})")
            if not email_csv:
                pending.append(f"Correos (retries: {email_retries})")
            emit(f"Poll {poll} ({elapsed}s) — esperando: {', '.join(pending)}")

        # If stuck, try refreshing
        if consecutive_empty_polls >= 20 and consecutive_empty_polls % 20 == 0:
            emit(f"[poll] {consecutive_empty_polls} polls vacíos, recargando página...")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=15_000)
                await asyncio.sleep(3)
            except Exception:
                pass

        # Close panel before next poll
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await asyncio.sleep(0.5)
        try:
            await page.mouse.click(500, 400)
        except Exception:
            pass

        await asyncio.sleep(current_interval)

    if need_people and not people_csv:
        raise TimeoutError(f"People CSV no disponible después de {max_wait}s ({people_retries} reintentos)")
    if not email_csv:
        raise TimeoutError(f"Email Activity CSV no disponible después de {max_wait}s ({email_retries} reintentos)")

    return people_csv, email_csv


async def _click_download_link(page, link_locator, dest: Path, emit=None) -> Path:
    """Click a download link locator and save the file. Retries up to 3 times."""
    last_error = None
    for attempt in range(1, 4):
        try:
            async with page.expect_download(timeout=60_000) as download_info:
                await link_locator.click()

            download = await download_info.value
            await download.save_as(str(dest))
            size = dest.stat().st_size
            msg = f"[scraper] {dest.name} descargado: {size:,} bytes"
            if emit:
                emit(msg)
            else:
                print(msg)
            if size == 0:
                raise ValueError(f"{dest.name} está vacío (0 bytes)")
            return dest
        except Exception as e:
            last_error = e
            msg = f"[download] Intento {attempt}/3 falló para {dest.name}: {e}"
            if emit:
                emit(msg)
            else:
                print(msg)
            if attempt < 3:
                await asyncio.sleep(3 + random.uniform(0, 2))
    raise last_error
