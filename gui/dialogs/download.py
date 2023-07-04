import io
import os
import wx
import time
import shutil
import struct
import urllib
import random
import wxasync
import tempfile
import traceback
import simplejson
from dataclasses import dataclass
from asyncio.locks import Event

from sd_model_manager.utils.common import try_load_image
from gui import ids, utils
from gui.api import ComfyAPI, ModelManagerAPI
from gui.utils import PROGRAM_ROOT, combine_tag_freq
from gui.comfy_executor import ComfyExecutor
from gui.image_panel import ImagePanel
from gui.async_utils import AsyncShowDialogModal, on_close

CHECKPOINTS = [
    "Based64Mix-v3",
    "Based64",
    "AbyssOrangeMix2_nsfw",
    "animefull",
    "animefull",
    "v1-5-",
]
VAES = ["animefull-latest", "kl-f8-anime", "vae-ft-mse"]

DEFAULT_POSITIVE_PROMPT = "masterpiece"
DEFAULT_NEGATIVE_PROMPT = "(worst quality, low quality:1.2)"


def load_prompt(name):
    with open(
        os.path.join(PROGRAM_ROOT, "gui/prompts", name), "r", encoding="utf-8"
    ) as f:
        return simplejson.load(f)


@dataclass
class GeneratePreviewsOptions:
    prompt_before: str
    prompt_after: str
    n_tags: int
    seed: int


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


def find_preview_images(basepath):
    i = 0
    images = []
    path = basepath + ".png"
    if os.path.isfile(path):
        images.append(path)

    while True:
        if i == 0:
            path = f"{basepath}.preview.png"
        else:
            path = f"{basepath}.preview.{i}.png"
        if not os.path.isfile(path):
            break
        images.append(path)
        i += 1

    return images


class PreviewGeneratorDialog(wx.Dialog):
    def __init__(self, parent, app, items, duplicate_op):
        super(PreviewGeneratorDialog, self).__init__(
            parent, -1, "Preview Generator", size=app.FromDIP(700, 500)
        )
        self.app = app
        self.comfy_api = ComfyAPI()
        self.duplicate_op = duplicate_op  # "replace", "append"

        utils.set_icons(self)

        tags = self.get_tags(items[0], count=20)
        if not tags:
            tags = ["1girl", "solo"]
        tags = ", ".join([t.strip() for t in tags])
        positive = ", ".join([DEFAULT_POSITIVE_PROMPT, tags])
        self.autogen = False

        # Parameter controls
        self.text_prompt_before = wx.TextCtrl(
            self,
            id=wx.ID_ANY,
            value=positive,
            size=self.Parent.FromDIP(wx.Size(250, 100)),
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
        )
        self.text_prompt_after = wx.TextCtrl(
            self,
            id=wx.ID_ANY,
            value=DEFAULT_NEGATIVE_PROMPT,
            size=self.Parent.FromDIP(wx.Size(250, 100)),
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
        )

        # self.label_n_tags = wx.StaticText(self, wx.ID_ANY, label="# Top Tags")
        # self.spinner_n_tags = wx.SpinCtrl(
        #     self,
        #     id=wx.ID_ANY,
        #     value="",
        #     style=wx.SP_ARROW_KEYS,
        #     min=-1,
        #     max=100,
        #     initial=10,
        # )

        # tag_totals = combine_tag_freq(items[0].get("tag_frequency") or {})
        # if len(tag_totals) == 0:
        #     self.spinner_n_tags.Disable()
        #     self.spinner_n_tags.SetValue(0)

        self.spinner_seed = wx.SpinCtrl(
            self,
            id=wx.ID_ANY,
            value="",
            style=wx.SP_ARROW_KEYS,
            min=-1,
            max=2**16,
            initial=-1,
            size=self.Parent.FromDIP(wx.Size(100, 25)),
        )

        # Status controls/buttons
        self.status_text = wx.StaticText(self, -1, "Ready")
        self.gauge = wx.Gauge(self, -1, 100, size=app.FromDIP(800, 32))
        self.image_panel = ImagePanel(
            self, style=wx.SUNKEN_BORDER, size=app.FromDIP(512, 512)
        )
        self.button_regenerate = wx.Button(self, wx.ID_HELP, "Generate")
        # self.button_regenerate.Disable()
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
        self.upscaled = False
        self.last_seed = 0
        self.last_upscale_seed = 0
        self.node_text = ""

        self.Bind(wx.EVT_BUTTON, self.OnRegenerate, id=wx.ID_HELP)
        self.Bind(wx.EVT_BUTTON, self.OnUpscale, id=wx.ID_APPLY)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)
        self.text_prompt_before.Bind(wx.EVT_TEXT_ENTER, self.OnRegenerate)
        self.text_prompt_after.Bind(wx.EVT_TEXT_ENTER, self.OnRegenerate)
        wxasync.AsyncBind(wx.EVT_BUTTON, self.OnOK, self.button_ok, id=wx.ID_OK)
        wxasync.AsyncBind(wx.EVT_CLOSE, self.OnClose, self)

        sizerB = wx.StdDialogButtonSizer()
        sizerB.AddButton(self.button_regenerate)
        sizerB.AddButton(self.button_upscale)
        sizerB.AddButton(self.button_cancel)
        sizerB.AddButton(self.button_ok)
        sizerB.Realize()

        sizerLeft = wx.BoxSizer(wx.VERTICAL)
        sizerLeft.Add(self.image_panel)
        sizerLeft.AddSpacer(8)
        sizerLeft.Add(self.status_text)

        # sizerRightMid = wx.BoxSizer(wx.HORIZONTAL)
        # sizerRightMid.Add(
        #     self.label_n_tags,
        #     proportion=1,
        #     border=5,
        #     flag=wx.ALL,
        # )
        # sizerRightMid.Add(self.spinner_n_tags, proportion=1, flag=wx.ALL, border=5)

        sizerRightAfter = wx.BoxSizer(wx.HORIZONTAL)
        sizerRightAfter.Add(
            wx.StaticText(self, wx.ID_ANY, label="Seed"),
            proportion=0,
            border=5,
            flag=wx.ALL,
        )
        sizerRightAfter.Add(self.spinner_seed, proportion=1, flag=wx.ALL, border=5)
        sizerRightAfter.Add(
            wx.StaticText(self, wx.ID_ANY, label=f"Selected models: {len(self.items)}"),
            proportion=0,
            border=5,
            flag=wx.ALL,
        )

        sizerRight = wx.StaticBoxSizer(wx.VERTICAL, self, label="Parameters")
        sizerRight.Add(wx.StaticText(self, wx.ID_ANY, label="Positive"))
        sizerRight.Add(self.text_prompt_before, proportion=2, flag=wx.ALL | wx.EXPAND)
        # sizerRight.Add(sizerRightMid, proportion=1, flag=wx.ALL)
        sizerRight.Add(wx.StaticText(self, wx.ID_ANY, label="Negative"))
        sizerRight.Add(self.text_prompt_after, proportion=2, flag=wx.ALL | wx.EXPAND)
        sizerRight.Add(sizerRightAfter, proportion=1, flag=wx.ALL)

        sizerMain = wx.FlexGridSizer(1, 2, 10, 10)
        sizerMain.AddMany([(sizerLeft, 1), (sizerRight, 1, wx.EXPAND)])

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(sizerMain, 1, wx.EXPAND)
        sizer.AddSpacer(8)
        sizer.Add(self.gauge, 0, wx.LEFT | wx.RIGHT)
        sizer.AddSpacer(8)
        sizer.Add(sizerB, 0, wx.LEFT | wx.RIGHT)

        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(sizer, 1, wx.EXPAND | wx.ALL, 10)

        self.SetSizerAndFit(wrapper)

        # self.start_prompt()

    async def save_preview_image(self, item, result):
        self.app.SetStatusText("Saving preview...")
        self.status_text.SetLabel("Saving preview...")

        image_data = self.comfy_api.get_image(
            result["filename"], result["subfolder"], result["type"]
        )
        filepath = item["filepath"]
        basepath = os.path.splitext(filepath)[0]

        path = basepath + ".png"
        if os.path.exists(path):
            i = 0
            found = None
            while found is None:
                if i == 0:
                    p = f"{basepath}.preview.png"
                else:
                    p = f"{basepath}.preview.{i}.png"
                if not os.path.exists(p):
                    found = p
                i += 1

            if self.duplicate_op == "append":
                path = found
            else:  # replace
                shutil.move(path, found)

        # Write the image
        with open(path, "wb") as f:
            f.write(image_data)

        # Update the metadata
        new_images = find_preview_images(basepath)
        new_images = [
            {"filepath": path, "is_autogenerated": True} for path in new_images  # TODO
        ]

        changes = {"preview_images": new_images}
        print(changes)
        result = await self.app.api.update_lora(item["id"], changes)
        print(result)
        item["preview_images"] = new_images

        try_load_image.cache_clear()
        await self.app.frame.results_panel.refresh_one_item(item)

        self.app.SetStatusText(f"Saved preview to {path}")

    async def OnOK(self, evt):
        self.button_regenerate.Disable()
        self.button_upscale.Disable()
        self.button_cancel.Disable()
        self.button_ok.Disable()
        self.text_prompt_before.Disable()
        self.text_prompt_after.Disable()
        self.spinner_seed.Disable()

        if self.result is not None:
            await self.save_preview_image(self.items[0], self.result)

        if len(self.items) > 1:
            self.status_text.SetLabel(f"Generating previews...")

            upscaled = self.upscaled
            self.autogen = True
            for i, item in enumerate(self.items[1:]):
                filename = os.path.basename(item["filepath"])
                self.status_text.SetLabel(
                    f"Generating preview: {filename} ({i}/{len(self.items)-1})"
                )
                self.spinner_seed.SetValue(self.last_seed)
                e = Event()
                thread = self.start_prompt(item, e=e)
                await e.wait()
                if upscaled:
                    self.status_text.SetLabel("Starting upscale...")
                    self.spinner_seed.SetValue(self.last_upscale_seed)
                    e = Event()
                    thread = self.upscale_prompt(item, e=e)
                    await e.wait()
                if self.result is not None:
                    await self.save_preview_image(item, self.result)
        else:
            self.status_text.SetLabel("Done!")

        self.AsyncEndModal(wx.ID_OK)

    def OnCancel(self, evt):
        self.AsyncEndModal(wx.ID_CANCEL)

    async def OnClose(self, evt):
        if self.autogen:
            return
        await on_close(self, evt)

    def OnRegenerate(self, evt):
        self.status_text.SetLabel("Starting...")
        self.start_prompt(self.items[0])

    def OnUpscale(self, evt):
        self.status_text.SetLabel("Starting upscale...")
        self.upscale_prompt(self.items[0])

    def upscale_prompt(self, item, e=None):
        return utils.start_async_thread(self.run_upscale_prompt, item, e)

    def start_prompt(self, item, e=None):
        return utils.start_async_thread(self.run_prompt, item, e)

    async def run_prompt(self, item, e):
        try:
            self.do_execute(item)
        except CancelException:
            pass
        except Exception as ex:
            print(traceback.format_exc())
            if e is None:
                await self.on_fail(ex)
        if e is not None:
            e.set()

    async def run_upscale_prompt(self, item, e):
        try:
            self.do_upscale(item)
        except CancelException:
            pass
        except Exception as ex:
            print(traceback.format_exc())
            if e is None:
                await self.on_fail(ex)
        if e is not None:
            e.set()

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
        tags = []
        tag_freq = item.get("tag_frequency")
        if tag_freq is not None:
            totals = utils.combine_tag_freq(tag_freq)
            sort = list(sorted(totals.items(), key=lambda p: p[1], reverse=True))
            tags = [p[0] for p in sort]
            if count is not None:
                tags = tags[:count]
        return tags

    def get_prompt_options(self):
        return GeneratePreviewsOptions(
            self.text_prompt_before.GetValue(),
            self.text_prompt_after.GetValue(),
            20,
            self.spinner_seed.GetValue(),
        )

    def get_lora_name(self, item):
        filepath = item["filepath"]
        folder_name = "loras"
        lora_name = self.comfy_api.get_relative_path(folder_name, filepath)[
            "relative_path"
        ]
        if lora_name is None:
            raise RuntimeError(
                f"LoRA not found in ComfyUI models list.\nEnsure it's included under the list of paths to scan in the ComfyUI configuration.\n{filepath}"
            )
        return lora_name

    def assemble_prompt_data(self, item):
        options = self.get_prompt_options()

        lora_name = self.get_lora_name(item)

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

        if options.seed == -1:
            seed = random.randint(0, 2**16)
        else:
            seed = options.seed

        print(f"Seed: {seed}")

        positive = f"{options.prompt_before}"
        negative = options.prompt_after

        data = PreviewPromptData(seed, checkpoint, vae, positive, negative, lora_name)
        return data

    def enqueue_prompt_and_wait(self, executor, prompt):
        queue_result = executor.enqueue(prompt)
        prompt_id = queue_result["prompt_id"]

        while True:
            wx.Yield()
            if not self:
                # self was destroyed
                return

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
        self.upscaled = False
        # self.image_panel.Clear()
        self.button_regenerate.Disable()
        self.button_upscale.Disable()
        self.button_ok.Disable()

    def after_execute(self):
        if not self.autogen:
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

    def do_execute(self, item):
        self.before_execute()
        self.last_output = None

        with ComfyExecutor() as executor:
            data = self.assemble_prompt_data(item)
            prompt = data.to_prompt()
            prompt_id = self.enqueue_prompt_and_wait(executor, prompt)

        image, image_location = self.get_output_image(prompt_id)
        if image:
            self.image_panel.LoadBitmap(image.ConvertToBitmap())

        self.last_data = data
        self.last_output = image_location
        self.result = image_location
        self.last_seed = data.seed

        self.after_execute()

    def do_upscale(self, item):
        self.before_execute()

        with ComfyExecutor() as executor:
            data = self.assemble_prompt_data(item)
            prompt = data.to_hr_prompt(self.last_output)
            prompt_id = self.enqueue_prompt_and_wait(executor, prompt)

        image, image_location = self.get_output_image(prompt_id)
        if image:
            self.image_panel.LoadBitmap(image.ConvertToBitmap())

        self.last_data = data
        self.result = image_location
        self.last_upscale_seed = data.seed

        self.after_execute()
        self.upscaled = True

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
        # dialog.Destroy()
        self.AsyncEndModal(wx.ID_CANCEL)


def any_have_previews(items):
    count = 0

    for item in items:
        filepath = item["filepath"]
        basepath = os.path.splitext(filepath)[0]
        path = basepath + ".png"
        if os.path.exists(path):
            count += 1

    return count


async def run(app, items):
    if not items:
        return

    count = any_have_previews(items)
    op = "replace"

    if count > 0:
        dlg = wx.MessageDialog(
            app.frame,
            f"{count} models already have preview files. Do you want to replace them or add them to the preview images list?",
            "Existing Previews",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Replace", "Append")
        result = await wxasync.AsyncShowDialogModal(dlg)
        if result == wx.ID_CANCEL:
            return
        op = "replace" if result == wx.ID_YES else "append"

    dialog = PreviewGeneratorDialog(app.frame, app, items, op)
    dialog.Center()
    result = await AsyncShowDialogModal(dialog)
    # dialog.Destroy()
