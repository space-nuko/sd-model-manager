import uuid
import json
import urllib.request
import urllib.parse
import os
import websocket
import simplejson

from gui.utils import PROGRAM_ROOT


class ComfyExecutor:
    def __init__(self):
        self.server_address = "127.0.0.1:8188"
        self.client_id = str(uuid.uuid4())
        self.ws = None

    def __enter__(self):
        self.ws = websocket.WebSocket()
        self.ws.connect(
            "ws://{}/ws?clientId={}".format(self.server_address, self.client_id)
        )
        return self

    def __exit__(self, type, value, traceback):
        self.ws.close()

    def enqueue(self, prompt_json):
        p = {"prompt": prompt_json, "client_id": self.client_id, "number": 10000}
        data = json.dumps(p).encode("utf-8")
        req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def get_status(self):
        out = self.ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            return {"type": "json", "data": message}
        else:
            return {"type": "binary", "data": out}
