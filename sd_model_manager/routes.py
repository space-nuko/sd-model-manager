import pathlib

from aiohttp import web

from sd_model_manager.main.views import routes as main_routes
from sd_model_manager.api.views import routes as api_routes

PROJECT_PATH = pathlib.Path(__file__).parent


def init_routes(app: web.Application) -> None:
    app.add_routes(main_routes)
    app.add_routes(api_routes)

    app.router.add_static("/static/", path=(PROJECT_PATH / "static"), name="static")
