from dataclasses import dataclass
import aiohttp
import simplejson

import wx
import wx.aui


class ModelManagerAPI:
    def __init__(self, config):
        self.config = config
        self.client = aiohttp.ClientSession()

    def base_url(self):
        host = self.config.listen
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.config.port}"

    async def get_loras(self, query):
        params = {
            "limit": 1000
        }
        if query:
            params["query"] = query

        async with self.client.get(self.base_url() + "/api/v1/loras", params=params) as response:
            if response.status != 200:
                print(await response.text())
            return await response.json()

    async def update_lora(self, id, changes):
        async with self.client.patch(self.base_url() + f"/api/v1/lora/{id}", data=simplejson.dumps({"changes": changes})) as response:
            return await response.json()
