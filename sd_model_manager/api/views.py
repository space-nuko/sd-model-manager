import os
from aiohttp import web
from sqlalchemy import create_engine, select, or_
from sqlalchemy.orm import Session, selectinload, selectin_polymorphic
from sqlakeyset.asyncio import select_page
import simplejson

from sd_model_manager.models.sd_models import (
    PreviewImage,
    PreviewImageSchema,
    SDModel,
    LoRAModel,
    LoRAModelSchema,
)
from sd_model_manager.query import build_search_query


def paging_to_json(paging, limit):
    return {
        "next": paging.bookmark_next,
        "current": paging.bookmark_current,
        "previous": paging.bookmark_previous,
        "limit": limit,
    }


routes = web.RouteTableDef()


@routes.get("/api/v1/preview_image/{id}")
async def show_preview_image(request):
    image_id = request.match_info.get("id", None)
    if image_id is None:
        return web.Response(status=404)

    async with request.app["sdmm_db"].AsyncSession() as s:
        query = select(PreviewImage).filter(PreviewImage.id == image_id)

        row = (await s.execute(query)).one()
        if row is None:
            return web.json_response(
                {"message": f"Preview image not found: {image_id}"}, status=404
            )
        row = row[0]

        schema = PreviewImageSchema()

        resp = {"data": schema.dump(row)}

        return web.json_response(resp, dumps=simplejson.dumps)


@routes.get("/api/v1/preview_image/{id}/view")
async def view_preview_image_file(request):
    image_id = request.match_info.get("id", None)
    if image_id is None:
        return web.Response(status=404)

    async with request.app["sdmm_db"].AsyncSession() as s:
        query = select(PreviewImage).filter(PreviewImage.id == image_id)

        row = (await s.execute(query)).one()
        if row is None:
            return web.Response(status=404)
        row = row[0]

        if not os.path.isfile(row.filepath):
            return web.Response(status=404)

        with open(row.filepath, "rb") as b:
            return web.Response(body=b.read(), content_type="image/jpeg")


@routes.get("/api/v1/loras")
async def index_loras(request):
    page_marker = request.rel_url.query.get("page", None)
    limit = int(request.rel_url.query.get("limit", 100))
    search_query = request.rel_url.query.get("query", None)

    async with request.app["sdmm_db"].AsyncSession() as s:
        query = select(LoRAModel)
        if search_query:
            query = build_search_query(query, search_query)
        query = query.options(selectin_polymorphic(SDModel, [LoRAModel])).options(
            selectinload(SDModel.preview_images)
        )

        page = await select_page(s, query, per_page=limit, page=page_marker)

        schema = LoRAModelSchema()

        resp = {
            "paging": paging_to_json(page.paging, limit),
            "data": [schema.dump(m[0]) for m in page],
        }

        return web.json_response(resp, dumps=simplejson.dumps)


@routes.get("/api/v1/lora/{id}")
async def show_loras(request):
    model_id = request.match_info.get("id", None)
    if model_id is None:
        return web.Response(status=404)

    async with request.app["sdmm_db"].AsyncSession() as s:
        query = select(LoRAModel).filter(LoRAModel.id == model_id)
        query = query.options(selectin_polymorphic(SDModel, [LoRAModel])).options(
            selectinload(SDModel.preview_images)
        )

        row = (await s.execute(query)).one()
        if row is None:
            return web.json_response(
                {"message": f"LoRA not found: {model_id}"}, status=404
            )
        row = row[0]

        schema = LoRAModelSchema()

        resp = {"data": schema.dump(row)}

        return web.json_response(resp, dumps=simplejson.dumps)


@routes.patch("/api/v1/lora/{id}")
async def update_lora(request):
    model_id = request.match_info.get("id", None)
    if model_id is None:
        return web.json_response({"message": "No LoRA ID provided"}, status=404)

    data = await request.json()
    changes = data.get("changes", None)

    if changes is None:
        return web.Response(status=400)

    async with request.app["sdmm_db"].AsyncSession() as s:
        query = select(LoRAModel).filter(LoRAModel.id == model_id)
        query = query.options(selectin_polymorphic(SDModel, [LoRAModel])).options(
            selectinload(SDModel.preview_images)
        )

        row = (await s.execute(query)).one()
        if row is None:
            return web.json_response(
                {"message": f"LoRA not found: {model_id}"}, status=404
            )
        row = row[0]

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

        if "preview_images" in changes:
            row.preview_images = []
            await s.flush()

            new_images = []
            for image in changes["preview_images"]:
                if "id" in image:
                    existing = await s.get(PreviewImage, image["id"])
                    if existing is None:
                        return web.json_response(
                            {"message": f"Preview image not found: {image['id']}"},
                            status=404,
                        )
                    for k, v in image.items():
                        if k == "filepath":
                            v = os.path.normpath(v)
                        setattr(existing, k, v)
                    new_images.append(existing)
                else:
                    new_image = PreviewImage(
                        filepath=os.path.normpath(image["filepath"]),
                        is_autogenerated=image.get("is_autogenerated", False),
                        model_id=row.id,
                    )
                    new_images.append(new_image)
                    s.add(new_image)
            row.preview_images = new_images
            updated += 1

        await s.commit()

        resp = {"status": "ok", "fields_updated": updated}

        return web.json_response(resp, dumps=simplejson.dumps)
