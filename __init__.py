# Entrypoint for use as a ComfyUI extension

import os
import sys
import inspect
import asyncio

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__))))

from sd_model_manager.db import DB
from sd_model_manager.api.views import routes as api_routes
from sd_model_manager.utils.common import get_config


def is_comfyui():
    for i in inspect.stack(0):
        filename = os.path.basename(i[1])
        function = i.function
        if filename == "nodes.py" and function == "load_custom_node":
            return True
    return False


async def initialize_comfyui():
    print("[SD-Model-Manager] Initializing...")

    import server
    from aiohttp import web
    import aiohttp

    prompt_server = server.PromptServer.instance

    for route in api_routes:
        prompt_server.routes._items.append(
            web.RouteDef(
                route.method, "/models" + route.path, route.handler, route.kwargs
            )
        )

    app = prompt_server.app
    app["sdmm_config"] = get_config([])

    db = DB()
    await db.init(app["sdmm_config"].model_paths)
    await db.scan(app["sdmm_config"].model_paths)
    app["sdmm_db"] = db

    print("[SD-Model-Manager] Initialized via ComfyUI server.")


if not is_comfyui():
    raise RuntimeError(
        "This script was not run from ComfyUI, use client.py for a standalone GUI instead"
    )


asyncio.run(initialize_comfyui())


NODE_CLASS_MAPPINGS = {}
__all__ = ["NODE_CLASS_MAPPINGS"]
