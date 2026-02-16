"""Playwright scraper for Reply.io - downloads People CSV + Email Activity CSV"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright


async def download_reports(
    email: str,
    password: str,
    team_id: int,
    download_dir: Path,
    on_progress=None,
    headless: bool = True,
) -> dict[str, Path]:
    """
    Downloads 2 CSVs from Reply.io:
    1. People CSV (All_prospects.csv) - via People > Select All > More > Export to CSV > Basic fields
    2. Email Activity CSV - via Reports/Emails > Filter Last Year > Export contact CSV

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

        # ═══════════════════════════════════════
        # REPORT 1: People CSV (Basic fields)
        # ═══════════════════════════════════════
        emit("Descargando reporte de Personas...")
        people_csv = await _download_people_csv(page, download_dir)

        # ═══════════════════════════════════════
        # REPORT 2: Email Activity CSV (contact-specific)
        # ═══════════════════════════════════════
        emit("Descargando reporte de Correos (contact-specific)...")
        email_csv = await _download_email_activity_csv(page, download_dir, emit)

        await browser.close()

        return {"personas": people_csv, "correos": email_csv}


async def _download_people_csv(page, download_dir: Path) -> Path:
    """People > All tab > Select All in list > More > Export to CSV > Basic fields"""

    await page.goto(
        "https://run.reply.io/Dashboard/Material#/people/list",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await asyncio.sleep(5)

    # Click "All" tab
    await page.locator('text=/^All\\s*\\(/').first.click()
    await asyncio.sleep(2)

    # Click the "All" dropdown (select-control-button)
    await page.locator('[data-test-id="select-control-button"]').click()
    await asyncio.sleep(1)

    # Click "All in list"
    await page.locator("text=All in list").first.click()
    await asyncio.sleep(2)

    # Click "More" dropdown
    await page.locator('button:has-text("More"):visible').first.click()
    await asyncio.sleep(1)

    # Hover "Export to CSV" (hover shows submenu, click closes it)
    await page.locator("text=Export to CSV").hover()
    await asyncio.sleep(1)

    # Click "Basic fields" — triggers direct download
    async with page.expect_download(timeout=60_000) as download_info:
        await page.locator("text=/^Basic fields$/").first.click()

    download = await download_info.value
    dest = download_dir / "people.csv"
    await download.save_as(str(dest))
    return dest


async def _download_email_activity_csv(page, download_dir: Path, emit, max_export_attempts: int = 4) -> Path:
    """Reports/Emails > Filter Last Year > Export contact CSV > poll Notification center.
    Retries the full export up to max_export_attempts times, polling 5 min each."""

    await page.goto(
        "https://run.reply.io/Dashboard/Material#/reports/emails",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await asyncio.sleep(5)

    # Open Filters panel
    await page.locator('[data-test-id="filters-drawer-toggle-button"]').click()
    await asyncio.sleep(1)

    # Expand Date filter
    await page.locator("text=Date").first.click()
    await asyncio.sleep(1)

    # Select "Last Year"
    await page.locator("text=Last Year").first.click()
    await asyncio.sleep(1)

    # Click Apply
    await page.locator('button:has-text("Apply")').click()
    await asyncio.sleep(5)

    # Close Filters
    await page.locator('[data-test-id="filters-drawer-toggle-button"]').click()
    await asyncio.sleep(1)

    all_export_times = []
    for export_attempt in range(1, max_export_attempts + 1):
        emit(f"Triggering export (intento {export_attempt}/{max_export_attempts})...")

        # Record time before export
        export_time = datetime.now()
        all_export_times.append(export_time)

        # Click Export dropdown
        await page.locator('button:has-text("Export"):visible').first.click()
        await asyncio.sleep(1)

        # Select "Export contact CSV"
        await page.locator("text=Export contact CSV").click()
        await asyncio.sleep(0.5)

        # Click Export button inside the popover
        export_btn = page.locator('.MuiPopover-paper button:has-text("Export"), .MuiPaper-root button:has-text("Export")')
        if await export_btn.count() > 0:
            await export_btn.first.click()
        else:
            await page.locator('button:has-text("Export"):visible').last.click()

        await asyncio.sleep(3)

        # Poll Notification center for download link (5 min max, every 5s)
        emit("Export en cola, esperando notificación...")
        dest = await _poll_notification_download(page, download_dir, all_export_times, emit)
        if dest:
            return dest

        emit(f"No se encontró descarga en 5 min, reintentando...")

    raise TimeoutError(f"Export no disponible después de {max_export_attempts} intentos")


async def _poll_notification_download(
    page, download_dir: Path, all_export_times: list[datetime], emit
) -> Path | None:
    """
    Poll the Notification center (sidebar bell icon) for 5 min every 5s.
    Accepts notifications matching ANY of the previous export times.
    Returns Path if download succeeded, None if timed out.
    """
    max_wait = 300  # 5 min
    poll_interval = 5

    # Build acceptable timestamps in 12h format from ALL export attempts
    acceptable_times = []
    for export_time in all_export_times:
        for offset_min in range(7):
            t = export_time.replace(second=0) + timedelta(minutes=offset_min)
            h = t.hour
            ampm = "AM" if h < 12 else "PM"
            h12 = 12 if h == 0 else (h - 12 if h > 12 else h)
            ts = f"{h12:02d}:{t.strftime('%M')} {ampm}"
            if ts not in acceptable_times:
                acceptable_times.append(ts)

    # Bell icon xpath (sidebar notification bell)
    bell = page.locator('xpath=/html/body/div[1]/div[1]/div[2]/div/div/div[2]/div[3]')

    start = datetime.now()
    poll = 0

    while (datetime.now() - start).total_seconds() < max_wait:
        poll += 1

        # Click notification bell
        try:
            await bell.click(timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Scan for "here"/"here." download links with timestamp validation
        result = await page.evaluate("""(acceptableTimes) => {
            const links = document.querySelectorAll('a');
            const downloadLinks = [];
            for (const link of links) {
                const txt = link.textContent.trim().toLowerCase();
                if ((txt === 'here' || txt === 'here.') && link.offsetWidth > 0) {
                    let container = link.closest('div');
                    let ctx = '';
                    let el = container;
                    for (let i = 0; i < 5 && el; i++) {
                        ctx = (el.textContent || '').trim();
                        if (ctx.includes('AM') || ctx.includes('PM')) break;
                        el = el.parentElement;
                    }
                    const matchesTime = acceptableTimes.some(t => ctx.includes(t));
                    downloadLinks.push({ href: link.href, context: ctx.substring(0, 200), matchesTime });
                }
            }
            return downloadLinks;
        }""", acceptable_times)

        # Check for time-matched link
        if result:
            matching = [dl for dl in result if dl['matchesTime']]
            if matching:
                target = matching[0]
                emit(f"Descarga disponible (poll {poll}): {target['context'][:80]}")

                here_link = page.locator(f'a[href="{target["href"]}"]:visible').first
                if await here_link.count() == 0:
                    here_link = page.locator('a:has-text("here"):visible').first

                async with page.expect_download(timeout=60_000) as download_info:
                    await here_link.click()

                download = await download_info.value
                dest = download_dir / "email_activity.csv"
                await download.save_as(str(dest))
                return dest

        # Close notification panel before next poll
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        await page.mouse.click(500, 400)

        elapsed = int((datetime.now() - start).total_seconds())
        if poll % 12 == 0:  # ~every 60s
            emit(f"Esperando export... ({elapsed}s)")

        await asyncio.sleep(poll_interval)

    return None
