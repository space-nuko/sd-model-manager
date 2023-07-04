import io
import os
import wx
import time
import struct
import urllib
import random
import wxasync
import tempfile
import traceback
import simplejson
from dataclasses import dataclass

from sd_model_manager.utils.common import try_load_image
from gui import ids, utils
from gui.api import ComfyAPI, ModelManagerAPI
from gui.utils import PROGRAM_ROOT
from gui.comfy_executor import ComfyExecutor
from gui.image_panel import ImagePanel
from gui.async_utils import AsyncShowDialogModal, on_close

CHECKPOINTS = [
    "Based64Mix-v3",
    "Based64",
    "AbyssOrangeMix2_nsfw",
    "animefull-latest",
    "animefull-final-pruned",
    "v1-5-pruned-emaonly",
]
VAES = ["animefull-latest", "kl-f8-anime", "vae-ft-mse"]


def load_prompt(name):
    with open(
        os.path.join(PROGRAM_ROOT, "gui/prompts", name), "r", encoding="utf-8"
    ) as f:
        return simplejson.load(f)


@dataclass
class PreviewPromptData:
    seed: int
    checkpoint: str
    vae: str
    positive: str
    negative: str
    lora_name: str

    def to_prompt(self):
        prompt = load_prompt("default.json")

        prompt["3"]["inputs"]["seed"] = self.seed
        prompt["4"]["inputs"]["ckpt_name"] = self.checkpoint
        prompt["11"]["inputs"]["vae_name"] = self.vae
        prompt["6"]["inputs"]["text"] = self.positive
        prompt["7"]["inputs"]["text"] = self.negative
        prompt["10"]["inputs"]["lora_name"] = self.lora_name

        return prompt

    def to_hr_prompt(self, image):
        prompt = load_prompt("hr.json")
        filename = image["filename"]

        prompt["11"]["inputs"]["seed"] = self.seed
        prompt["16"]["inputs"]["ckpt_name"] = self.checkpoint
        prompt["17"]["inputs"]["vae_name"] = self.vae
        prompt["6"]["inputs"]["text"] = self.positive
        prompt["7"]["inputs"]["text"] = self.negative
        prompt["21"]["inputs"]["lora_name"] = self.lora_name
        prompt["18"]["inputs"]["image"] = f"{filename} [output]"

        return prompt


class CancelException(Exception):
    pass


class PreviewGeneratorDialog(wx.Dialog):
    def __init__(self, parent, app, items):
        super(PreviewGeneratorDialog, self).__init__(parent, -1, "Preview Generator")
        self.app = app
        self.comfy_api = ComfyAPI()

        # util.set_icon(self)

        self.status_text = wx.StaticText(self, -1, "Starting...")
        self.gauge = wx.Gauge(self, -1, 100, size=app.FromDIP(400, 32))
        self.image_panel = ImagePanel(
            self, style=wx.SUNKEN_BORDER, size=app.FromDIP(512, 512)
        )
        self.button_regenerate = wx.Button(self, wx.ID_HELP, "Regenerate")
        self.button_regenerate.Disable()
        self.button_upscale = wx.Button(self, wx.ID_APPLY, "Upscale")
        self.button_upscale.Disable()
        self.button_cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        self.button_ok = wx.Button(self, wx.ID_OK, "OK")
        self.button_ok.Disable()

        self.items = items
        self.result = None
        self.last_data = None
        self.last_output = None
        self.executing_node_id = None
        self.node_text = ""

        self.Bind(wx.EVT_BUTTON, self.OnRegenerate, id=wx.ID_HELP)
        self.Bind(wx.EVT_BUTTON, self.OnUpscale, id=wx.ID_APPLY)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnOK, self.button_ok, id=wx.ID_OK)
        wxasync.AsyncBind(wx.EVT_CLOSE, self.OnClose, self)

        sizerB = wx.StdDialogButtonSizer()
        sizerB.AddButton(self.button_regenerate)
        sizerB.AddButton(self.button_upscale)
        sizerB.AddButton(self.button_cancel)
        sizerB.AddButton(self.button_ok)
        sizerB.Realize()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.image_panel)
        sizer.AddSpacer(8)
        sizer.Add(self.status_text)
        sizer.AddSpacer(8)
        sizer.Add(self.gauge, 0, wx.EXPAND)
        sizer.AddSpacer(8)
        sizer.Add(sizerB, 0, wx.EXPAND)

        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(sizer, 1, wx.EXPAND | wx.ALL, 10)

        self.SetSizerAndFit(wrapper)

        self.start_prompt()

    async def save_preview_image(self, item, result):
        self.app.SetStatusText("Saving preview...")
        self.status_text.SetLabel("Saving preview...")

        image_data = self.comfy_api.get_image(
            result["filename"], result["subfolder"], result["type"]
        )
        filepath = os.path.join(item["root_path"], item["filepath"])
        basepath = os.path.splitext(filepath)[0]
        found = None
        for ext in [".png"]:
            path = basepath + ext
            if not os.path.exists(path):
                found = path
                break

        i = 0
        while found is None:
            if i == 0:
                path = f"{basepath}.preview.png"
            else:
                path = f"{basepath}.preview.{i}.png"
            if not os.path.exists(path):
                found = path
            i += 1

        # Update the metadata
        # new_images = item.get("preview_images") or []
        # new_images = [i for i in new_images if os.path.isfile(i["filepath"])]
        new_images = []
        new_images.append({"filepath": found, "is_autogenerated": True})

        changes = {"preview_images": new_images}
        print(changes)
        result = await self.app.api.update_lora(item["id"], changes)
        print(result)
        item["preview_images"] = new_images

        # Write the image
        with open(path, "wb") as f:
            f.write(image_data)

        try_load_image.cache_clear()
        await self.app.frame.results_panel.refresh_one_item(item)

        self.app.SetStatusText(f"Saved preview to {found}")
        self.status_text.SetLabel("Done!")

    async def OnOK(self, evt):
        self.button_regenerate.Disable()
        self.button_upscale.Disable()
        self.button_cancel.Disable()
        self.button_ok.Disable()

        # TODO more than one image
        if self.result is not None:
            await self.save_preview_image(self.items[0], self.result)

        self.AsyncEndModal(wx.ID_OK)

    def OnCancel(self, evt):
        self.AsyncEndModal(wx.ID_CANCEL)

    async def OnClose(self, evt):
        await on_close(self, evt)

    def OnRegenerate(self, evt):
        if self.last_data is not None:
            self.last_data.seed = random.randint(0, 2**16)
        self.start_prompt(data=self.last_data)

    def OnUpscale(self, evt):
        self.last_data.seed = random.randint(0, 2**16)
        utils.start_async_thread(self.upscale_prompt, self.last_data)

    def start_prompt(self, data=None):
        utils.start_async_thread(self.run_prompt, data)

    async def run_prompt(self, data):
        try:
            self.do_execute(data)
        except CancelException:
            pass
        except Exception as ex:
            print(traceback.format_exc())
            await self.on_fail(ex)

    async def upscale_prompt(self, data):
        try:
            self.do_upscale(data)
        except CancelException:
            pass
        except Exception as ex:
            print(traceback.format_exc())
            await self.on_fail(ex)

    def find_checkpoint(self):
        checkpoints = self.comfy_api.get_filepaths("checkpoints")["filepaths"]
        if not checkpoints:
            return None
        for name in CHECKPOINTS:
            name = name.lower()
            for ckpt in checkpoints:
                if os.path.basename(ckpt).lower().startswith(name):
                    return ckpt
        print(
            f"WARNING: Couldn't find recommended checkpoint, using first in list: {checkpoints[0]}"
        )
        return checkpoints[0]

    def find_vae(self):
        vaes = self.comfy_api.get_filepaths("vae")["filepaths"]
        if not vaes:
            return None
        for name in VAES:
            name = name.lower()
            for vae in vaes:
                if os.path.basename(vae).lower().startswith(name):
                    return vae
        print(f"WARNING: Couldn't find recommended VAE, using first in list: {vaes[0]}")
        return vaes[0]

    def get_tags(self, item, count=None):
        tags = ["1girl", "solo", "cowboy shot"]
        tag_freq = item.get("tag_frequency")
        if tag_freq is not None:
            totals = utils.combine_tag_freq(tag_freq)
            sort = list(sorted(totals.items(), key=lambda p: p[1], reverse=True))
            tags = [p[0] for p in sort]
            if count is not None:
                tags = tags[:count]
        return tags

    def assemble_prompt_data(self, item):
        filepath = os.path.join(item["root_path"], item["filepath"])
        folder_name = "loras"
        lora_name = self.comfy_api.get_relative_path(folder_name, filepath)[
            "relative_path"
        ]
        if lora_name is None:
            raise RuntimeError(
                f"LoRA not found in ComfyUI models list.\nEnsure it's included under the list of paths to scan in the ComfyUI configuration.\n{filepath}"
            )

        checkpoint = self.find_checkpoint()
        if checkpoint is None:
            raise RuntimeError(
                f"Couldn't find a Stable Diffusion checkpoint to use from this list:\n{', '.join(CHECKPOINTS)}"
            )

        vae = self.find_vae()
        if vae is None:
            raise RuntimeError(
                f"Couldn't find a Stable Diffusion VAE to use from this list:\n{', '.join(VAES)}"
            )

        seed = random.randint(0, 2**16)

        tags = self.get_tags(item, count=20)
        tags = ", ".join(tags)

        positive = f"""
masterpiece,
{tags}
"""

        negative = f"""
(worst quality, low quality:1.2), censored, bar censoring, mosaic censoring
"""

        data = PreviewPromptData(seed, checkpoint, vae, positive, negative, lora_name)
        return data

    def enqueue_prompt_and_wait(self, executor, prompt):
        queue_result = executor.enqueue(prompt)
        prompt_id = queue_result["prompt_id"]

        while True:
            msg = executor.get_status()
            if msg:
                if msg["type"] == "json":
                    status = msg["data"]
                    print(status)
                    ty = status["type"]
                    if ty == "executing":
                        data = status["data"]
                        if data["node"] is not None:
                            self.on_msg_executing(prompt, data)
                        else:
                            if data["prompt_id"] == prompt_id:
                                # Execution is done
                                break
                    elif ty == "progress":
                        self.on_msg_progress(status)
                else:
                    msg = io.BytesIO(msg["data"])
                    ty = struct.unpack(">I", msg.read(4))[0]
                    if ty == 1:  # preview image
                        format = struct.unpack(">I", msg.read(4))[0]
                        if format == 2:
                            img_type = wx.BITMAP_TYPE_PNG
                        else:  # 1
                            img_type = wx.BITMAP_TYPE_JPEG
                        image = wx.Image(msg, type=img_type)
                        self.image_panel.LoadBitmap(image.ConvertToBitmap())

        return prompt_id

    def before_execute(self):
        self.result = None
        self.last_data = None
        self.image_panel.Clear()
        self.button_regenerate.Disable()
        self.button_upscale.Disable()
        self.button_ok.Disable()

    def after_execute(self):
        self.button_regenerate.Enable()
        self.button_ok.Enable()
        self.button_upscale.Enable()
        self.status_text.SetLabel("Finished.")

    def get_output_image(self, prompt_id):
        images, files = self.comfy_api.get_images(prompt_id)
        if not images:
            return None, None
        image_datas = []
        image_files = None
        for node_id in images:
            image_datas += images[node_id]
            image_files = files[node_id]
        if not image_datas:
            return None, None
        return wx.Image(io.BytesIO(image_datas[0])), image_files[0]

    def do_execute(self, data):
        self.before_execute()
        self.last_output = None

        with ComfyExecutor() as executor:
            item = self.items[0]
            if data is None:
                data = self.assemble_prompt_data(item)

            prompt = data.to_prompt()
            prompt_id = self.enqueue_prompt_and_wait(executor, prompt)

        image, image_location = self.get_output_image(prompt_id)
        if image:
            self.image_panel.LoadBitmap(image.ConvertToBitmap())

        self.last_data = data
        self.last_output = image_location
        self.result = image_location

        self.after_execute()

    def do_upscale(self, data):
        self.before_execute()

        with ComfyExecutor() as executor:
            prompt = data.to_hr_prompt(self.last_output)
            prompt_id = self.enqueue_prompt_and_wait(executor, prompt)

        image, image_location = self.get_output_image(prompt_id)
        if image:
            self.image_panel.LoadBitmap(image.ConvertToBitmap())

        self.last_data = data
        self.result = image_location

        self.after_execute()

    def on_msg_executing(self, prompt, data):
        node_id = data["node"]
        self.executing_node_id = node_id
        class_type = prompt[node_id]["class_type"]
        self.node_text = f"Node: {class_type}"
        self.status_text.SetLabel(self.node_text)
        self.gauge.SetRange(100)
        self.gauge.SetValue(0)

    def on_msg_progress(self, status):
        value = status["data"]["value"]
        max = status["data"]["max"]
        self.status_text.SetLabel(f"{self.node_text} ({value}/{max})")
        self.gauge.SetRange(max)
        self.gauge.SetValue(value)

    async def on_fail(self, ex):
        dialog = wx.MessageDialog(
            self,
            f"Failed to generate previews:\n{ex}",
            "Generation Failed",
            wx.OK | wx.ICON_ERROR,
        )
        await wxasync.AsyncShowDialogModal(dialog)
        dialog.Destroy()
        self.AsyncEndModal(wx.ID_CANCEL)


async def run(app, items):
    dialog = PreviewGeneratorDialog(app.frame, app, items)
    dialog.Center()
    result = await AsyncShowDialogModal(dialog)
    dialog.Destroy()
