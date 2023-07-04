from dataclasses import dataclass

import wx


@dataclass
class GeneratePreviewsOptions:
    prompt_before: str
    prompt_after: str
    n_tags: int
    deduplicate: bool
    seed: int


class GeneratePreviewsDialog(wx.Dialog):
    def __init__(self, parent, selection, app=None):
        super().__init__(
            parent=parent,
            id=wx.ID_ANY,
            title="Generate Previews",
            size=parent.FromDIP(wx.Size(600, 500)),
        )

        self.SetEscapeId(12345)

        self.selection = selection
        self.app = app
        self.result = None

        self.text_prompt_before = wx.TextCtrl(
            self, id=wx.ID_ANY, size=self.Parent.FromDIP(wx.Size(250, 140))
        )
        self.text_prompt_after = wx.TextCtrl(
            self, id=wx.ID_ANY, size=self.Parent.FromDIP(wx.Size(250, 140))
        )

        self.spinner_n_tags = wx.SpinCtrl(
            self,
            id=wx.ID_ANY,
            value="",
            style=wx.SP_ARROW_KEYS,
            min=-1,
            max=100,
            initial=10,
        )
        self.checkbox_deduplicate = wx.CheckBox(
            self, id=wx.ID_ANY, label="Deduplicate", style=0
        )
        self.checkbox_deduplicate.SetValue(True)

        self.spinner_seed = wx.SpinCtrl(
            self,
            id=wx.ID_ANY,
            value="",
            style=wx.SP_ARROW_KEYS,
            min=-1,
            max=2**32,
            initial=0,
        )

        self.sizerMid = wx.BoxSizer(wx.HORIZONTAL)
        self.sizerMid.Add(
            wx.StaticText(self, label="# Top Tags"), proportion=1, border=2, flag=wx.ALL
        )
        self.sizerMid.Add(self.spinner_n_tags, proportion=1, border=2, flag=wx.ALL)
        self.sizerMid.Add(
            self.checkbox_deduplicate, proportion=1, border=2, flag=wx.ALL
        )

        self.sizerAfter = wx.BoxSizer(wx.HORIZONTAL)
        self.sizerAfter.Add(
            wx.StaticText(self, label="Seed"), proportion=1, border=2, flag=wx.ALL
        )
        self.sizerAfter.Add(self.spinner_seed, proportion=1, flag=wx.ALL)

        self.sizerMain = wx.BoxSizer(wx.VERTICAL)
        self.sizerMain.Add(
            self.text_prompt_before, proportion=2, flag=wx.ALL | wx.EXPAND
        )
        self.sizerMain.Add(self.sizerMid, proportion=1, flag=wx.ALL)
        self.sizerMain.Add(
            self.text_prompt_after, proportion=2, flag=wx.ALL | wx.EXPAND
        )
        self.sizerMain.Add(self.sizerAfter, proportion=1, flag=wx.ALL)

        self.buttonOK = wx.Button(self, wx.ID_OK)
        self.buttonCancel = wx.Button(self, wx.ID_CANCEL)

        self.Bind(wx.EVT_BUTTON, self.OnConfirm, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)

        self.sizerB = wx.StdDialogButtonSizer()
        self.sizerB.AddButton(self.buttonOK)
        self.sizerB.AddButton(self.buttonCancel)
        self.sizerB.Realize()

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(
            self.sizerMain,
            proportion=10,
            border=2,
            flag=wx.EXPAND | wx.ALIGN_TOP | wx.ALL,
        )
        self.sizer.Add(self.sizerB, border=2, flag=wx.EXPAND | wx.ALL)

        self.SetSizer(self.sizer)

    def OnConfirm(self, evt):
        self.result = GeneratePreviewsOptions(
            self.text_prompt_before.GetValue(),
            self.text_prompt_after.GetValue(),
            self.spinner_n_tags.GetValue(),
            self.checkbox_deduplicate.GetValue(),
            self.spinner_seed.GetValue(),
        )
        self.EndModal(wx.ID_OK)

    def OnCancel(self, evt):
        self.EndModal(wx.ID_CANCEL)
