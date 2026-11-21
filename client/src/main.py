"""Run the same Flet client as a native desktop app or a browser preview."""

import argparse
import logging
import os

import flet as ft
from cinema_client.app import CinemaApp


async def main(page: ft.Page) -> None:
    """Create a separate application/session for each Flet window."""
    await CinemaApp(page).start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Кинотеатр — десктопный и мобильный клиент")
    parser.add_argument("--web", action="store_true", help="Открыть браузерный предпросмотр")
    parser.add_argument(
        "--no-browser", action="store_true", help="Не открывать браузер автоматически"
    )
    parser.add_argument("--port", type=int, default=8550, help="Порт браузерного предпросмотра")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.web and args.no_browser:
        # Flet's view=None otherwise selects a raw TCP desktop session, not HTTP.
        os.environ["FLET_FORCE_WEB_SERVER"] = "true"
    ft.run(
        main,
        view=(None if args.no_browser else ft.AppView.WEB_BROWSER)
        if args.web
        else ft.AppView.FLET_APP,
        host="127.0.0.1",
        port=args.port if args.web else 0,
        no_cdn=True,
    )
