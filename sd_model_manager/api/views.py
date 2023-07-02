import sys
from aiohttp import web
from sqlalchemy import create_engine, select, or_
from sqlalchemy.orm import Session, selectin_polymorphic
from sqlakeyset.asyncio import select_page
import simplejson

from sd_model_manager.models.sd_models import SDModel, LoRAModel, LoRAModelSchema

def paging_to_json(paging, limit):
    return {
        "next": paging.bookmark_next,
        "current": paging.bookmark_current,
        "previous": paging.bookmark_previous,
        "limit": limit
    }

routes = web.RouteTableDef()

@routes.get("/api/v1/loras")
async def index(request):
    page_marker = request.rel_url.query.get("page", None)
    limit = int(request.rel_url.query.get("limit", sys.maxsize))
    search_query = request.rel_url.query.get("query", None)

    async with request.app["db"].AsyncSession() as s:
        query = select(LoRAModel)
        if search_query:
            query = query.where(
                or_(
                    SDModel.display_name.contains(search_query),
                    SDModel.filepath.contains(search_query)
                )
            )
        query = query.order_by(SDModel.id).options(selectin_polymorphic(SDModel, [LoRAModel]))

        page = await select_page(s, query, per_page=limit, page=page_marker)

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

    async with request.app["db"].AsyncSession() as s:
        row = await s.get(LoRAModel, model_id)
        if row is None:
            return web.Response(status=404)

        schema = LoRAModelSchema()

        resp = {
            "data": schema.dump(row)
        }

        return web.json_response(resp, dumps=simplejson.dumps)

@routes.patch("/api/v1/lora/{id}")
async def update(request):
    model_id = request.match_info.get("id", None)
    if model_id is None:
        return web.json_response({"message": "No LoRA ID provided"}, status=404)

    data = await request.json()
    changes = data.get("changes", None)

    if changes is None:
        return web.Response(status=400)

    async with request.app["db"].AsyncSession() as s:
        row = await s.get(LoRAModel, model_id)
        if row is None:
            return web.json_response({"message": f"LoRA not found: {id}"}, status=404)

        updated = 0

        if "display_name" in changes:
            row.display_name = changes["display_name"]
            updated += 1
        if "author" in changes:
            row.author = changes["author"]
            updated += 1
        if "source" in changes:
            row.source = changes["source"]
            updated += 1
        if "tags" in changes:
            row.tags = changes["tags"]
            updated += 1
        if "keywords" in changes:
            row.keywords = changes["keywords"]
            updated += 1
        if "rating" in changes:
            row.rating = changes["rating"]
            updated += 1

        await s.commit()

        resp = {
            "status": "ok",
            "fields_updated": updated
        }

        return web.json_response(resp, dumps=simplejson.dumps)
