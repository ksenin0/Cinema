"""Render the real Flutter UI and exercise checkout against an isolated demo backend.

Run only against the throwaway server described in docs/client.md. Output screenshots
and the result marker are written to .qa/client-visual/. No real user account is used.
"""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

import flet as ft

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "client" / "src"))

from cinema_client.app import CinemaApp  # noqa: E402

OUTPUT = PROJECT_ROOT / ".qa" / "client-visual"


async def main(page: ft.Page) -> None:
    """Capture desktop/mobile layouts and exercise the real reserve/pay button handlers."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "result.json").unlink(missing_ok=True)
    app = CinemaApp(page)
    try:
        await app.start()
        page.title = "Кинотеатр · проверка интерфейса"
        page.window.min_height = 300
        root = page.controls.pop()
        screenshot = ft.Screenshot(root, expand=True)
        page.add(screenshot)

        async def capture(name: str, width: int = 390, height: int = 844) -> None:
            """Resize the native Flutter window, wait for layout, and save the rendered pixels."""
            page.window.width, page.window.height = width, height
            page.update()
            await asyncio.sleep(0.8)
            data = await screenshot.capture(pixel_ratio=1.0, delay=500)
            (OUTPUT / f"{name}.png").write_bytes(data)
            print(f"Captured {name}", flush=True)

        await capture("catalog-desktop", 1180, 850)
        await capture("catalog-mobile", 390, 844)
        await app.open("auth", {"mode": "register"})
        await capture("registration-mobile")
        await app.api.login("visual_demo", "DemoCinema482!")
        movie = (await app.api.movies())[0]
        await app.open_movie(movie)
        await capture("movie-desktop", 1180, 850)
        session = (await app.api.sessions(movie.id))[0]
        await app.open_seats(session)
        seats_screen = app.view
        free_seats = [seat for seat in seats_screen.matrix.seats if seat.status == "free"]
        for seat in free_seats[:2]:
            await app.event(seats_screen.toggle, seat)()
        await capture("seats-mobile")
        await capture("seats-landscape", 844, 390)
        await seats_screen.pay_button.on_click()
        assert seats_screen.order and seats_screen.order.status == "pending"
        await capture("checkout-mobile")
        await seats_screen.pay_button.on_click()
        assert app.view.order.status == "paid"
        await capture("ticket-mobile")
        await app.open("orders")
        await capture("orders-desktop", 1180, 850)
        await app.open("profile")
        await capture("profile-mobile")
        (OUTPUT / "result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
        print("Visual checkout smoke passed", flush=True)
    except Exception:
        error = traceback.format_exc()
        print(error, flush=True)
        (OUTPUT / "result.json").write_text(
            json.dumps({"success": False, "error": error}), encoding="utf-8"
        )
    finally:
        await app.close()
        await page.window.close()


if __name__ == "__main__":
    os.environ.setdefault("CINEMA_API_URL", "http://127.0.0.1:8001/api/v1/")
    ft.run(main, no_cdn=True)
    marker = OUTPUT / "result.json"
    if not marker.exists() or not json.loads(marker.read_text(encoding="utf-8"))["success"]:
        raise SystemExit(1)
