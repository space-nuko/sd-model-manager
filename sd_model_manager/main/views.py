from typing import Dict

import aiohttp_jinja2
import markdown2
from aiohttp import web

from sd_model_manager.constants import PROJECT_DIR

routes = web.RouteTableDef()

@routes.get("/")
@aiohttp_jinja2.template('index.html')
async def index(request: web.Request) -> Dict[str, str]:
    with open(PROJECT_DIR / 'README.md') as f:
        text = markdown2.markdown(f.read())

    return {"text": text}
