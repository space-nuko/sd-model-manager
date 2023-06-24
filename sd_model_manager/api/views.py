from aiohttp import web
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectin_polymorphic
from sqlakeyset.asyncio import select_page
import simplejson

from sd_model_manager.models.sd_models import SDModel, LoRAModel, LoRAModelSchema

def paging_to_json(paging, limit):
    return {
        "next": paging.next,
        "current": paging.current,
        "previous": paging.previous,
        "limit": limit
    }

routes = web.RouteTableDef()

@routes.get("/api/v1/loras")
async def index(request):
    page_no = int(request.rel_url.query.get("page_no", 0))
    limit = int(request.rel_url.query.get("limit", 20))

    async with request.app["db"].AsyncSession() as s:
        query = select(SDModel).order_by(LoRAModel.filepath, SDModel.id).options(selectin_polymorphic(SDModel, [LoRAModel]))
        page = await select_page(s, query, per_page=limit, page=page_no)

        schema = LoRAModelSchema()

        resp = {
            "paging": paging_to_json(page.paging, limit),
            "data": [schema.dump(m[0]) for m in page]
        }

        return web.json_response(resp, dumps=simplejson.dumps)

@routes.get("/api/v1/lora/{id}")
async def show(request):
    model_id = request.match_info.get("id", None)
    if model_id is None:
        return web.Response(status=404)

    resp = {"test": "a"}
    return web.json_response(resp)
