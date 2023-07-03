import os
import subprocess
import re
import io
import aiopubsub
from typing import Callable

import wx
import wx.aui
import wx.lib.newevent

from sd_model_manager.utils.common import find_image, try_load_image


PUBSUB_HUB = aiopubsub.Hub()


def trim_string(s, n=200):
    return (s[:n] + "...") if len(s) > n else s

def open_on_file(path):
    path = os.path.realpath(path)

    if os.name == 'nt':
        explorer = os.path.join(os.getenv('WINDIR'), 'explorer.exe')
        subprocess.run([explorer, '/select,', path])
    else:
        os.startfile(os.path.dirname(path))

def load_bitmap(path):
    with open(path, "rb") as f:
        img = wx.Image(io.BytesIO(f.read()), type=wx.BITMAP_TYPE_ANY, index=-1)
        return wx.Bitmap(img, depth=wx.BITMAP_SCREEN_DEPTH)

def find_image_for_model(item):
    image = None
    image_path = None

    image_paths = item["preview_images"]
    if len(image_paths) > 0:
        for path in image_paths:
            image = try_load_image(path["filepath"])
            if image is not None:
                image_path = path["filepath"]
                break

    if image is None:
        filepath = os.path.normpath(os.path.join(item["root_path"], item["filepath"]))
        image, image_path = find_image(filepath, load=True)

    return image, image_path

def find_image_path_for_model(item):
    image_path = None

    image_paths = item["preview_images"]
    if len(image_paths) > 0:
        for path in image_paths:
            if os.path.isfile(path["filepath"]):
                return path["filepath"]

    filepath = os.path.normpath(os.path.join(item["root_path"], item["filepath"]))
    _, image_path = find_image(filepath, load=False)
    return image_path

def combine_tag_freq(tags):
    totals = {}
    for folder, freqs in tags.items():
        for tag, freq in freqs.items():
            if tag not in totals:
                totals[tag] = 0
            totals[tag] += freq
    return totals

class ColumnInfo:
    name: str
    callback: Callable
    width: int
    is_meta: bool
    is_visible: bool

    def __init__(self, name, callback, width=None, is_meta=False, is_visible=True):
        self.name = name
        self.callback = callback
        self.width = width
        self.is_meta = is_meta

        self.is_visible = is_visible

def format_rating(rating):
    if rating is None or rating <= 0:
        return ""
    rating = min(10, max(0, int(rating)))
    return u'\u2605'*int(rating/2) + u'\u00BD'*int(rating%2!=0)


re_optimizer = re.compile(r'([^.]+)(\(.*\))?$')


def format_optimizer(m):
    optimizer = m["optimizer"]
    if optimizer is None:
        return None

    matches = re_optimizer.search(optimizer)
    if matches is None:
        return optimizer
    return matches[1]


def format_optimizer_args(m):
    optimizer = m["optimizer"]
    if optimizer is None:
        return None

    matches = re_optimizer.search(optimizer)
    if matches is None or matches[2] is None:
        return None
    return matches[2].lstrip("(").rstrip(")")

    # result = {}
    # for pair in args.split(","):
    #     spl = pair.split("=", 1)
    #     if len(spl) > 1:
    #         result[spl[0]] = spl[1]

    # return str(result)


def format_network_alpha(v):
    try:
        return int(float(v))
    except Exception:
        try:
            return float(v)
        except Exception:
            return v

COLUMNS = [
    # ColumnInfo("ID", lambda m: m["id"]),
    ColumnInfo("Has Image", lambda m: "★" if len(m["preview_images"] or []) > 0 else "", width=20),
    ColumnInfo("Filename", lambda m: os.path.basename(m["filepath"]), width=240),

    ColumnInfo("Module", lambda m: m["module_name"], width=60),

    ColumnInfo("Name", lambda m: m["display_name"], is_meta=True, width=100),
    ColumnInfo("Author", lambda m: m["author"], is_meta=True, width=100),
    ColumnInfo("Rating", lambda m: format_rating(m["rating"]), is_meta=True, width=60),

    ColumnInfo("Dim.", lambda m: format_network_alpha(m["network_dim"]), width=60),
    ColumnInfo("Alpha", lambda m: format_network_alpha(m["network_alpha"]), width=60),
    ColumnInfo("Resolution", lambda m: m["resolution_width"]),
    ColumnInfo("Unique Tags", lambda m: m["unique_tags"]),
    ColumnInfo("Learning Rate", lambda m: m["learning_rate"]),
    ColumnInfo("UNet LR", lambda m: m["unet_lr"]),
    ColumnInfo("Text Encoder LR", lambda m: m["text_encoder_lr"]),
    ColumnInfo("Optimizer", format_optimizer, width=120),
    ColumnInfo("Optimizer Args", format_optimizer_args, width=240),
    ColumnInfo("Scheduler", lambda m: m["lr_scheduler"], width=80),
    ColumnInfo("# Train Images", lambda m: m["num_train_images"]),
    ColumnInfo("# Reg Images", lambda m: m["num_reg_images"]),
    ColumnInfo("# Batches/Epoch", lambda m: m["num_batches_per_epoch"]),
    ColumnInfo("# Epochs", lambda m: m["num_epochs"]),
    ColumnInfo("Epoch", lambda m: m["epoch"]),
    ColumnInfo("Total Batch Size", lambda m: m["total_batch_size"]),
    ColumnInfo("Keep Tokens", lambda m: m["keep_tokens"]),
    ColumnInfo("Noise Offset", lambda m: m["noise_offset"]),
    ColumnInfo("Training Comment", lambda m: m["training_comment"], width=140, is_visible=False),

    ColumnInfo("Tags", lambda m: m["tags"], is_meta=True, width=140),
    ColumnInfo("Keywords", lambda m: m["keywords"], is_meta=True, width=140, is_visible=False),
    ColumnInfo("Source", lambda m: m["source"], is_meta=True, width=100, is_visible=False),

    ColumnInfo("Filepath", lambda m: os.path.normpath(os.path.join(m["root_path"], m["filepath"])), width=600),
]
