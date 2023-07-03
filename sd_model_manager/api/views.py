import sys
from aiohttp import web
from sqlalchemy import create_engine, select, or_
from sqlalchemy.orm import Session, selectin_polymorphic
from sqlakeyset.asyncio import select_page
import simplejson

from sd_model_manager.models.sd_models import SDModel, LoRAModel, LoRAModelSchema
from sd_model_manager.query import build_search_query

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
            query = build_search_query(query, search_query)
        query = query.options(selectin_polymorphic(SDModel, [LoRAModel]))

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

        fields = [
            "display_name",
            "version",
            "author",
            "source",
            "tags",
            "keywords",
            "negative_keywords",
            "description",
            "notes",
            "rating",
        ]

        for field in fields:
            if field in changes:
                setattr(row, field, changes[field])
                updated += 1

        await s.commit()

        resp = {
            "status": "ok",
            "fields_updated": updated
        }

        return web.json_response(resp, dumps=simplejson.dumps)
