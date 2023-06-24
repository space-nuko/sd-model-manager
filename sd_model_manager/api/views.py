from aiohttp import web

routes = web.RouteTableDef()

@routes.get('/api/v1/models')
async def index(request):
    resp = [
        {"test": "a"},
        {"test": "b"},
        {"test": "c"}
    ]

    return web.json_response(resp)

@routes.get('/api/v1/model/{id}')
async def show(request):
    model_id = request.match_info.get("id", None)
    if model_id is None:
        return web.Response(status=404)

    resp = {"test": "a"}
    return web.json_response(resp)
