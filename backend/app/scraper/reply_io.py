"""Playwright scraper for Reply.io - downloads People CSV + Email Activity CSV"""
import asyncio
import random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright


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
        browser = await p.chromium.launch(headless=headless)
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


async def download_all_reports(
    email: str,
    password: str,
    clients: list[dict],
    on_progress=None,
    headless: bool = True,
) -> dict[str, dict]:
    """
    Single login, iterates through all clients reusing the same browser session.
    Each client only does a workspace switch, no new login.

    Args:
        clients: [{"client_id": str, "team_id": int, "download_dir": Path}, ...]

    Returns:
        {client_id: {"personas": Path, "correos": Path}} for successes,
        {client_id: {"error": str}} for failures.
    """

    def emit(msg: str):
        if on_progress:
            on_progress(msg)
        print(msg)

    results: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
        )
        page = await context.new_page()
        page2 = await context.new_page()

        # ── LOGIN ONCE ──
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
        emit(f"Sesión iniciada. Procesando {len(clients)} clientes...")

        # ── LOOP CLIENTS ──
        for idx, client in enumerate(clients, 1):
            cid = client["client_id"]
            team_id = client["team_id"]
            download_dir = Path(client["download_dir"])
            download_dir.mkdir(parents=True, exist_ok=True)

            def emit_client(msg, _cid=cid, _idx=idx):
                emit(f"[{_idx}/{len(clients)}] {_cid}: {msg}")

            try:
                emit_client(f"Cambiando a workspace {team_id}...")
                await page.goto(
                    f"https://run.reply.io/Home/SwitchTeam?teamId={team_id}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                await asyncio.sleep(8)

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

            except Exception as e:
                import traceback
                traceback.print_exc()
                emit_client(f"ERROR: {e}")
                results[cid] = {"error": str(e)}

        await page2.close()
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
        print(msg)

    download_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=200 if not headless else 0)
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
        await page.goto(
            f"https://run.reply.io/Home/SwitchTeam?teamId={team_id}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await asyncio.sleep(8)

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
    await asyncio.sleep(1)

    await page.locator("text=Date").first.click(timeout=10_000)
    await asyncio.sleep(1)
    await page.locator("text=Last Year").first.click(timeout=10_000)
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
