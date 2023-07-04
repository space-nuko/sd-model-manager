import wx
import wx.aui
import wx.lib.newevent
from wx.lib.agw import ultimatelistctrl


from gui.popup_menu import PopupMenu, PopupMenuItem
from gui.utils import trim_string


IGNORE_FIELDS = set(
    [
        "preview_images",
        "tag_frequency",
        "dataset_dirs",
        "reg_dataset_dirs",
        "bucket_info",
        "name",
        "author",
        "rating",
        "tags",
        "keywords",
        "source",
        "_index",
        "id",
        "type",
    ]
)

METADATA_ORDER = [
    "output_name",
    "root_path",
    "filepath",
    "training_started_at",
    "training_finished_at",
    "session_id",
    "learning_rate",
    "text_encoder_lr",
    "unet_lr",
    "num_train_images",
    "num_reg_images",
    "num_batches_per_epoch",
    "max_train_steps",
    "lr_warmup_steps",
    "batch_size_per_device",
    "total_batch_size",
    "num_epochs",
    "epoch",
    "gradient_checkpointing",
    "gradient_accumulation_steps",
    "optimizer",
    "lr_scheduler",
    "network_module",
    "network_dim",
    "network_alpha",
    "network_args",
    "mixed_precision",
    "full_fp16",
    "v2",
    "resolution_width",
    "resolution_height",
    "clip_skip",
    "max_token_length",
    "color_aug",
    "flip_aug",
    "random_crop",
    "shuffle_caption",
    "cache_latents",
    "enable_bucket",
    "min_bucket_reso",
    "max_bucket_reso",
    "seed",
    "keep_tokens",
    "noise_offset",
    "max_grad_norm",
    "caption_dropout_rate",
    "caption_dropout_every_n_epochs",
    "caption_tag_dropout_rate",
    "face_crop_aug_range",
    "prior_loss_weight",
    "min_snr_gamma",
    "scale_weight_norms",
    "unique_tags",
    "model_hash",
    "legacy_hash",
    "sd_model_name",
    "sd_model_hash",
    "new_sd_model_hash",
    "vae_name",
    "vae_hash",
    "new_vae_hash",
    "vae_name",
    "training_comment",
    "sd_scripts_commit_hash",
]


class MetadataList(ultimatelistctrl.UltimateListCtrl):
    def __init__(self, parent, item, app=None):
        super().__init__(
            parent=parent,
            id=wx.ID_ANY,
            agwStyle=ultimatelistctrl.ULC_VIRTUAL
            | ultimatelistctrl.ULC_REPORT
            | wx.LC_HRULES
            | wx.LC_VRULES,
        )

        self.item = item
        self.app = app

        self.InsertColumn(0, "Key")
        self.InsertColumn(1, "Value")
        self.SetColumnWidth(0, parent.FromDIP(140))
        self.SetColumnWidth(1, ultimatelistctrl.ULC_AUTOSIZE_FILL)

        self.fields = [(k, v) for k, v in self.item.items() if k in METADATA_ORDER]
        self.fields = list(
            sorted(self.fields, key=lambda i: METADATA_ORDER.index(i[0]))
        )

        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnListItemRightClicked)

        self.SetItemCount(len(self.fields))

    def OnGetItemColumnImage(self, item, col):
        return []

    def OnGetItemImage(self, item):
        return []

    def OnGetItemAttr(self, item):
        return None

    def OnGetItemText(self, item, col):
        v = self.fields[item][col]
        if col == 1:
            if v is None:
                return "(None)"
            elif isinstance(v, str):
                return f'"{v}"'
        return str(v)

    def OnGetItemTextColour(self, item, col):
        v = self.fields[item][col]
        if col == 1 and v is None:
            return "gray"
        return None

    def OnGetItemToolTip(self, item, col):
        return None

    def OnGetItemKind(self, item):
        return 0

    def OnGetItemColumnKind(self, item, col):
        return 0

    def ClearSelection(self):
        i = self.GetFirstSelected()
        while i != -1:
            self.Select(i, 0)
            i = self.GetNextSelected(i)

    def OnListItemRightClicked(self, evt):
        self.ClearSelection()
        self.Select(evt.GetIndex())

        target = self.fields[evt.GetIndex()]

        menu = PopupMenu(
            target=target,
            event=evt,
            items=[PopupMenuItem("Copy Value", self.copy_value)],
        )
        pos = evt.GetPoint()
        self.PopupMenu(menu, pos)
        menu.Destroy()

    def copy_value(self, target, event):
        value = target[event.GetColumn()]

        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(str(value)))
            wx.TheClipboard.Close()

            self.app.frame.statusbar.SetStatusText(f"Copied: {trim_string(value)}")


class MetadataDialog(wx.Dialog):
    def __init__(self, parent, item, app=None):
        super().__init__(
            parent=parent,
            id=wx.ID_ANY,
            title="Model Metadata",
            size=parent.FromDIP(wx.Size(600, 700)),
        )

        self.SetEscapeId(12345)

        self.item = item
        self.app = app

        self.list = MetadataList(self, item, app=self.app)
        self.buttonOk = wx.Button(self, wx.ID_OK)

        self.sizerB = wx.StdDialogButtonSizer()
        self.sizerB.AddButton(self.buttonOk)
        self.sizerB.Realize()

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(
            self.list, proportion=10, border=2, flag=wx.EXPAND | wx.ALIGN_TOP | wx.ALL
        )
        self.sizer.Add(self.sizerB, border=2, flag=wx.EXPAND | wx.ALL)

        self.SetSizer(self.sizer)
