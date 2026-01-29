from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, Tuple

from pearlalgo.utils.logger import logger

DEFAULT_VIEWPORT: Tuple[int, int] = (1200, 800)


async def capture_live_chart_screenshot(
    *,
    output_path: Path,
    url: str,
    viewport: Tuple[int, int] = DEFAULT_VIEWPORT,
    timeout_ms: int = 20_000,
    wait_for_selector: str = '[data-chart-ready="true"]',
    extra_wait_seconds: float = 1.0,
) -> Optional[Path]:
    """
    Capture a PNG screenshot of the Live Main Chart.

    Returns `output_path` on success, or None on failure.

    Notes:
    - Requires Playwright:
        pip install playwright && playwright install chromium
    - `url` must be reachable from this process.
    - Waits for data-chart-ready="true" attribute which indicates chart data is loaded.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.parent / f".{output_path.name}.tmp"

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        logger.warning(
            "Playwright not installed. Install with: pip install playwright && playwright install chromium"
        )
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(
                viewport={"width": int(viewport[0]), "height": int(viewport[1])}
            )

            await page.goto(url, wait_until="networkidle", timeout=int(timeout_ms))
            
            # Wait for chart to be fully loaded (data-chart-ready="true")
            try:
                await page.wait_for_selector(wait_for_selector, timeout=int(timeout_ms))
                logger.debug("Chart ready indicator found")
            except Exception:
                # Fallback: wait for canvas if chart-ready not found
                logger.debug(f"Chart ready selector not found, falling back to canvas")
                try:
                    await page.wait_for_selector("canvas", timeout=5000)
                except Exception:
                    pass

            if extra_wait_seconds and extra_wait_seconds > 0:
                await asyncio.sleep(float(extra_wait_seconds))

            await page.screenshot(path=str(tmp_path), type="png")
            await browser.close()

        if not tmp_path.exists():
            return None

        os.replace(str(tmp_path), str(output_path))
        return output_path if output_path.exists() else None
    except Exception as e:
        logger.error(f"Failed to capture live chart screenshot: {e}")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None

