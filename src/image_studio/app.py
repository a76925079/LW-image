from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import Canvas, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from .api_client import ApiError, ChatGPT2ApiClient
from .config import ConfigStore
from .history import HistoryStore
from .models import AppConfig, HistoryRecord, ThemeMode


APP_DISPLAY_NAME = "T8-电商小红书配图工具"
QUALITY_MAP = {"自动": "auto", "高": "high", "中": "medium", "低": "low"}
ANNOUNCEMENT_TEXT = "公告：本产品为社媒年卡用户专享，不对外销售，如果你是付费购买的请立即退款。"
RATIOS = {
    "1:1": (1024, 1024),
    "3:2": (1536, 1024),
    "2:3": (1024, 1536),
    "4:3": (1365, 1024),
    "3:4": (1024, 1365),
    "9:16": (1024, 1820),
    "16:9": (1820, 1024),
}


@dataclass(frozen=True, slots=True)
class ThemePalette:
    bg: str
    panel: str
    panel_alt: str
    surface: str
    border: str
    text: str
    muted: str
    input: str
    accent: str
    accent_hover: str
    danger: str


class AppTheme:
    palettes = {
        "dark": ThemePalette(
            bg="#111111",
            panel="#161616",
            panel_alt="#1d1d1d",
            surface="#141414",
            border="#343434",
            text="#f3f3f3",
            muted="#8d8d8d",
            input="#201d1d",
            accent="#2f8cff",
            accent_hover="#1d74d8",
            danger="#c94b4b",
        ),
        "light": ThemePalette(
            bg="#f5f6f8",
            panel="#ffffff",
            panel_alt="#f1f3f5",
            surface="#ffffff",
            border="#d7dce2",
            text="#1f2328",
            muted="#6d7682",
            input="#f6f7f9",
            accent="#1769e0",
            accent_hover="#0f57bd",
            danger="#c33d3d",
        ),
    }

    def __init__(self, mode: ThemeMode) -> None:
        self.mode = mode

    @property
    def palette(self) -> ThemePalette:
        return self.palettes[self.mode]

    def apply(self) -> None:
        ctk.set_appearance_mode("Dark" if self.mode == "dark" else "Light")
        ctk.set_default_color_theme("blue")


class ImageStudioApp(ctk.CTk):
    def __init__(self) -> None:
        self.config_store = ConfigStore()
        self.config_data = self.config_store.load()
        self.theme = AppTheme(self.config_data.theme)
        self.theme.apply()

        super().__init__()
        self.title(APP_DISPLAY_NAME)
        self._apply_window_icon()
        self.geometry("1280x820")
        self.minsize(1100, 720)

        self.history_store = HistoryStore()
        self.edit_image_path: Path | None = None
        self.current_results: list[Path] = []
        self.is_busy = False

        self._build_ui()
        self._load_config_to_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.topbar = TopBar(self, self)
        self.topbar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))

        self.workspace = ctk.CTkFrame(self, corner_radius=10)
        self.workspace.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.workspace.grid_columnconfigure(0, minsize=392)
        self.workspace.grid_columnconfigure(1, weight=1)
        self.workspace.grid_rowconfigure(0, weight=1)

        self.parameters = ParameterPanel(self.workspace, self)
        self.parameters.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.results = ResultCanvas(self.workspace, self)
        self.results.grid(row=0, column=1, sticky="nsew")

        self.status_var = ctk.StringVar(value="就绪")
        self.status_label = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 10))

    def _apply_window_icon(self) -> None:
        icon_path = resource_path("icon.ico")
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(str(icon_path))
        except Exception:
            pass

    def _load_config_to_ui(self) -> None:
        cfg = self.config_data
        self.parameters.model_var.set(cfg.default_model or "gpt-image-2")
        width, height = self._parse_size(cfg.default_size)
        self.parameters.width_var.set(str(width))
        self.parameters.height_var.set(str(height))
        self.topbar.set_announcement_text(ANNOUNCEMENT_TEXT)

    def _apply_theme(self) -> None:
        palette = self.theme.palette
        self.configure(fg_color=palette.bg)
        self.workspace.configure(fg_color=palette.bg)
        self.status_label.configure(text_color=palette.muted)
        self.topbar.apply_theme(palette)
        self.parameters.apply_theme(palette)
        self.results.apply_theme(palette)

    def toggle_theme(self) -> None:
        next_mode: ThemeMode = "light" if self.theme.mode == "dark" else "dark"
        self.theme = AppTheme(next_mode)
        self.theme.apply()
        self.config_data.theme = next_mode
        self.config_data = self.config_store.save(self.config_data)
        self._apply_theme()
        self._set_status("已切换到白天模式" if next_mode == "light" else "已切换到黑夜模式")

    def open_history(self) -> None:
        HistoryDialog(self, self.history_store, self.theme.palette, self.fill_from_history)

    def open_settings(self) -> None:
        SettingsDialog(self, self.config_store, self.config_data, self.theme.palette, self._on_settings_saved)

    def _on_settings_saved(self, config: AppConfig) -> None:
        self.config_data = config
        self._load_config_to_ui()
        self._set_status("设置已保存")

    def choose_reference_image(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if not selected:
            return
        self.edit_image_path = Path(selected)
        self.parameters.set_reference(self.edit_image_path)
        self._set_status("已选择参考图")

    def clear_reference_image(self) -> None:
        self.edit_image_path = None
        self.parameters.set_reference(None)
        self._set_status("已清除参考图，将使用文生图")

    def generate(self) -> None:
        prompt = self.parameters.prompt_value()
        if not prompt:
            messagebox.showwarning("缺少提示词", "请先输入提示词。")
            return
        try:
            width = int(self.parameters.width_var.get())
            height = int(self.parameters.height_var.get())
        except ValueError:
            messagebox.showwarning("尺寸不正确", "宽高必须是数字。")
            return

        model = self.parameters.model_var.get().strip() or "gpt-image-2"
        size = f"{width}x{height}"
        count = int(self.parameters.count_var.get())
        quality = QUALITY_MAP.get(self.parameters.quality_var.get(), "auto")
        reference = self.edit_image_path
        self._run_background(
            "正在生成图片...",
            lambda: self._do_generate(prompt, model, size, count, quality, reference),
        )

    def _do_generate(self, prompt: str, model: str, size: str, count: int, quality: str, reference: Path | None) -> None:
        client = self._current_client()
        output_dir = self.config_data.output_dir.expanduser()
        if reference:
            results, response = client.edit_image(
                image_path=reference,
                prompt=prompt,
                model=model,
                size=size,
                output_dir=output_dir,
                quality=quality,
            )
            kind = "image_to_image"
        else:
            results, response = client.generate_image(
                prompt=prompt,
                model=model,
                size=size,
                n=count,
                output_dir=output_dir,
                quality=quality,
            )
            kind = "text_to_image"

        paths = [item.path for item in results]
        self.history_store.add(kind=kind, prompt=prompt, model=model, size=size, image_paths=paths, response_json=response)
        self.current_results = paths
        self.after(0, lambda: self.results.show_images(paths, prompt))
        self.after(0, lambda: self._set_status(f"已生成 {len(paths)} 张图片"))

    def fill_from_history(self, record: HistoryRecord) -> None:
        self.parameters.set_prompt(record.prompt)
        self.parameters.model_var.set(record.model or "gpt-image-2")
        width, height = self._parse_size(record.size)
        self.parameters.width_var.set(str(width))
        self.parameters.height_var.set(str(height))
        if record.image_paths:
            self.results.show_images(record.image_paths, record.prompt)
        self._set_status(f"已填回历史 #{record.id}")

    def copy_path(self, path: Path) -> None:
        self.clipboard_clear()
        self.clipboard_append(str(path))
        self._set_status("图片路径已复制")

    def add_reference_from_result(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("文件不存在", str(path))
            return
        self.edit_image_path = path
        self.parameters.set_reference(path)
        self._set_status("已添加为参考图，下次生成将使用图生图")

    def open_parent_dir(self, path: Path) -> None:
        target = path.parent if path.suffix else path
        if target.exists():
            self.open_path(target)
        else:
            messagebox.showwarning("目录不存在", str(target))

    def _current_client(self) -> ChatGPT2ApiClient:
        return ChatGPT2ApiClient(self.config_data.base_url, self.config_data.api_key)

    def _run_background(self, status: str, target) -> None:
        if self.is_busy:
            return
        self.is_busy = True
        self._set_status(status)
        self.parameters.set_busy(True)
        self.results.show_loading()

        def runner() -> None:
            try:
                target()
            except ApiError as exc:
                self.after(0, lambda: self.results.show_empty("生成失败"))
                self.after(0, lambda: messagebox.showerror("接口错误", str(exc)))
                self.after(0, lambda: self._set_status("接口调用失败"))
            except Exception as exc:
                self.after(0, lambda: self.results.show_empty("运行失败"))
                self.after(0, lambda: messagebox.showerror("运行错误", str(exc)))
                self.after(0, lambda: self._set_status("运行失败"))
            finally:
                self.after(0, lambda: self.parameters.set_busy(False))
                self.after(0, self._clear_busy)

        threading.Thread(target=runner, daemon=True).start()

    def _clear_busy(self) -> None:
        self.is_busy = False

    def _set_status(self, value: str) -> None:
        self.status_var.set(value)

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        try:
            width, height = size.lower().split("x", 1)
            return int(width), int(height)
        except (ValueError, AttributeError):
            return 1024, 1024

    @staticmethod
    def open_path(path: Path) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            webbrowser.open(path.as_uri())


class TopBar(ctk.CTkFrame):
    def __init__(self, master, app: ImageStudioApp) -> None:
        super().__init__(master, corner_radius=8)
        self.app = app
        self.grid_columnconfigure(1, weight=1)
        self.title = ctk.CTkLabel(self, text=APP_DISPLAY_NAME, font=ctk.CTkFont(size=18, weight="bold"))
        self.title.grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self.announcement_banner = ctk.CTkFrame(self, corner_radius=8)
        self.announcement_banner.grid(row=0, column=1, sticky="ew", padx=10, pady=8)
        self.announcement_banner.grid_columnconfigure(0, weight=1)
        self.announcement_var = ctk.StringVar(value=ANNOUNCEMENT_TEXT)
        self.announcement = ctk.CTkLabel(self.announcement_banner, textvariable=self.announcement_var, anchor="center")
        self.announcement.grid(row=0, column=0, sticky="ew", padx=12, pady=6)
        self.theme_btn = ctk.CTkButton(self, text="白天/黑夜", width=96, command=app.toggle_theme)
        self.theme_btn.grid(row=0, column=2, padx=6, pady=10)
        self.history_btn = ctk.CTkButton(self, text="历史", width=72, command=app.open_history)
        self.history_btn.grid(row=0, column=3, padx=6, pady=10)
        self.settings_btn = ctk.CTkButton(self, text="设置", width=72, command=app.open_settings)
        self.settings_btn.grid(row=0, column=4, padx=(6, 14), pady=10)

    def set_announcement_text(self, text: str) -> None:
        self.announcement_var.set(text)

    def apply_theme(self, palette: ThemePalette) -> None:
        self.configure(fg_color=palette.panel, border_color=palette.border, border_width=1)
        self.title.configure(text_color=palette.text)
        banner_bg = "#241f16" if palette.bg == "#111111" else "#fff7e6"
        banner_border = "#5a4521" if palette.bg == "#111111" else "#f0c36d"
        banner_text = "#f5d08a" if palette.bg == "#111111" else "#7a4d00"
        self.announcement_banner.configure(fg_color=banner_bg, border_color=banner_border, border_width=1)
        self.announcement.configure(text_color=banner_text)
        for button in (self.theme_btn, self.history_btn, self.settings_btn):
            button.configure(fg_color=palette.panel_alt, hover_color=palette.input, border_color=palette.border, border_width=1, text_color=palette.text)


class ParameterPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, app: ImageStudioApp) -> None:
        super().__init__(master, corner_radius=10)
        self.app = app
        self.model_var = ctk.StringVar(value="gpt-image-2")
        self.quality_var = ctk.StringVar(value="自动")
        self.width_var = ctk.StringVar(value="1024")
        self.height_var = ctk.StringVar(value="1024")
        self.count_var = ctk.StringVar(value="1")
        self.reference_label_var = ctk.StringVar(value="暂无参考图")
        self.selected_ratio: str | None = "1:1"
        self._syncing_ratio = False
        self.ratio_buttons: dict[str, RatioButton] = {}
        self.palette: ThemePalette | None = None
        self.ref_preview_image: ctk.CTkImage | None = None

        self.grid_columnconfigure(0, weight=1)
        self.heading = ctk.CTkLabel(self, text="生图工作台", anchor="w", font=ctk.CTkFont(size=24, weight="bold"))
        self.heading.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 18))

        self._section_label("提示词", 1)
        self.prompt = ctk.CTkTextbox(self, height=150, corner_radius=8)
        self.prompt.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 18))
        self.prompt.insert("1.0", "描述画面主体、风格、构图、光线和用途")

        self._section_label("参考图", 3)
        ref_tools = ctk.CTkFrame(self, fg_color="transparent")
        ref_tools.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 8))
        ref_tools.grid_columnconfigure(0, weight=1)
        self.ref_label = ctk.CTkLabel(ref_tools, textvariable=self.reference_label_var, anchor="w")
        self.ref_label.grid(row=0, column=0, sticky="ew")
        self.upload_btn = ctk.CTkButton(ref_tools, text="上传", width=72, command=app.choose_reference_image)
        self.upload_btn.grid(row=0, column=1, padx=(8, 0))
        self.clear_ref_btn = ctk.CTkButton(ref_tools, text="清除", width=72, command=app.clear_reference_image)
        self.clear_ref_btn.grid(row=0, column=2, padx=(8, 0))
        self.ref_box = ctk.CTkFrame(self, height=118, corner_radius=8)
        self.ref_box.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.ref_box.grid_propagate(False)
        self.ref_box.grid_columnconfigure(1, weight=1)
        self.ref_preview = ctk.CTkLabel(self.ref_box, text="", width=92, height=92)
        self.ref_preview.grid(row=0, column=0, padx=12, pady=12)
        self.ref_empty = ctk.CTkLabel(self.ref_box, text="暂无参考图\n上传图片后将使用图生图", anchor="w", justify="left")
        self.ref_empty.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=12)

        self._section_label("模型", 6)
        self.model = ctk.CTkComboBox(self, variable=self.model_var, values=["gpt-image-2", "gpt-image-1"], height=34)
        self.model.grid(row=7, column=0, sticky="ew", padx=18, pady=(4, 16))

        self._section_label("质量", 8)
        self.quality = ctk.CTkSegmentedButton(self, variable=self.quality_var, values=["自动", "高", "中", "低"])
        self.quality.grid(row=9, column=0, sticky="ew", padx=18, pady=(4, 16))

        self._section_label("尺寸", 10)
        size_row = ctk.CTkFrame(self, fg_color="transparent")
        size_row.grid(row=11, column=0, sticky="ew", padx=18, pady=(4, 12))
        size_row.grid_columnconfigure((0, 2), weight=1)
        self.width_entry = ctk.CTkEntry(size_row, textvariable=self.width_var, height=36)
        self.width_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(size_row, text="x").grid(row=0, column=1, padx=10)
        self.height_entry = ctk.CTkEntry(size_row, textvariable=self.height_var, height=36)
        self.height_entry.grid(row=0, column=2, sticky="ew")

        ratio_grid = ctk.CTkFrame(self, fg_color="transparent")
        ratio_grid.grid(row=12, column=0, sticky="ew", padx=18, pady=(0, 16))
        ratio_grid.grid_columnconfigure((0, 1, 2, 3), weight=1)
        for index, label in enumerate(RATIOS):
            button = RatioButton(ratio_grid, label, RATIOS[label], lambda value=label: self.set_ratio(value))
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=5, pady=5)
            self.ratio_buttons[label] = button

        self.width_var.trace_add("write", lambda *_: self._sync_ratio_from_size())
        self.height_var.trace_add("write", lambda *_: self._sync_ratio_from_size())

        self._section_label("数量", 13)
        self.count = ctk.CTkSegmentedButton(self, variable=self.count_var, values=["1", "2", "3", "4"])
        self.count.grid(row=14, column=0, sticky="ew", padx=18, pady=(4, 18))

        self.generate_btn = ctk.CTkButton(self, text="生成图片", height=46, font=ctk.CTkFont(size=16, weight="bold"), command=app.generate)
        self.generate_btn.grid(row=15, column=0, sticky="ew", padx=18, pady=(0, 20))

    def _section_label(self, text: str, row: int) -> None:
        label = ctk.CTkLabel(self, text=text, anchor="w", font=ctk.CTkFont(size=14, weight="bold"))
        label.grid(row=row, column=0, sticky="ew", padx=18, pady=(4, 0))

    def prompt_value(self) -> str:
        value = self.prompt.get("1.0", "end").strip()
        return "" if value == "描述画面主体、风格、构图、光线和用途" else value

    def set_prompt(self, value: str) -> None:
        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", value)

    def set_reference(self, path: Path | None) -> None:
        self.reference_label_var.set(path.name if path else "暂无参考图")
        if not path:
            self.ref_preview_image = None
            self.ref_preview.configure(image=None, text="")
            self.ref_empty.configure(text="暂无参考图\n上传图片后将使用图生图")
            return
        try:
            image = Image.open(path)
            image.thumbnail((92, 92))
            self.ref_preview_image = ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=image.size)
            self.ref_preview.configure(image=self.ref_preview_image, text="")
            self.ref_empty.configure(text=f"{path.name}\n已作为参考图")
        except Exception:
            self.ref_preview_image = None
            self.ref_preview.configure(image=None, text="")
            self.ref_empty.configure(text=f"{path.name}\n预览失败，但仍会作为参考图")

    def set_ratio(self, label: str) -> None:
        width, height = RATIOS[label]
        self._syncing_ratio = True
        self.width_var.set(str(width))
        self.height_var.set(str(height))
        self._syncing_ratio = False
        self.selected_ratio = label
        self._refresh_ratio_buttons()

    def _sync_ratio_from_size(self) -> None:
        if self._syncing_ratio:
            return
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except ValueError:
            self.selected_ratio = None
            self._refresh_ratio_buttons()
            return
        self.selected_ratio = None
        for label, (ratio_width, ratio_height) in RATIOS.items():
            if width * ratio_height == height * ratio_width:
                self.selected_ratio = label
                break
        self._refresh_ratio_buttons()

    def _refresh_ratio_buttons(self) -> None:
        if not self.palette:
            return
        palette = self.palette
        for label, button in self.ratio_buttons.items():
            button.apply_theme(palette, label == self.selected_ratio)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (self.generate_btn, self.upload_btn, self.clear_ref_btn):
            widget.configure(state=state)

    def apply_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.configure(fg_color=palette.panel, border_color=palette.border, border_width=1)
        self.heading.configure(text_color=palette.text)
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                child.configure(text_color=palette.text)
        for widget in (self.prompt, self.width_entry, self.height_entry):
            widget.configure(fg_color=palette.input, border_color=palette.border, text_color=palette.text)
        self.model.configure(fg_color=palette.input, button_color=palette.panel_alt, button_hover_color=palette.input, border_color=palette.border, text_color=palette.text)
        self.quality.configure(fg_color=palette.panel_alt, selected_color=palette.accent, selected_hover_color=palette.accent_hover, unselected_color=palette.panel_alt, unselected_hover_color=palette.input, text_color=palette.text)
        self.count.configure(fg_color=palette.panel_alt, selected_color=palette.accent, selected_hover_color=palette.accent_hover, unselected_color=palette.panel_alt, unselected_hover_color=palette.input, text_color=palette.text)
        self.ref_box.configure(fg_color=palette.surface, border_color=palette.border, border_width=1)
        self.ref_empty.configure(text_color=palette.muted)
        self._refresh_ratio_buttons()
        for button in (self.upload_btn, self.clear_ref_btn):
            button.configure(fg_color=palette.panel_alt, hover_color=palette.input, border_color=palette.border, border_width=1, text_color=palette.text)
        self.generate_btn.configure(fg_color=palette.accent, hover_color=palette.accent_hover, text_color="#ffffff")


class RatioButton(ctk.CTkFrame):
    def __init__(self, master, label: str, ratio: tuple[int, int], command) -> None:
        super().__init__(master, corner_radius=8, height=58, cursor="hand2")
        self.label_text = label
        self.ratio = ratio
        self.command = command
        self.grid_columnconfigure(0, weight=1)
        self.canvas = Canvas(self, width=34, height=24, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, pady=(8, 0))
        self.label = ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=12, weight="bold"))
        self.label.grid(row=1, column=0, pady=(0, 7))
        for widget in (self, self.canvas, self.label):
            widget.bind("<Button-1>", self._on_click)

    def _on_click(self, _event=None) -> None:
        self.command()

    def apply_theme(self, palette: ThemePalette, selected: bool) -> None:
        bg = palette.accent if selected else palette.panel_alt
        border = palette.accent if selected else palette.border
        text = "#ffffff" if selected else palette.text
        icon = "#ffffff" if selected else palette.text
        self.configure(fg_color=bg, border_color=border, border_width=1)
        self.label.configure(text_color=text)
        self.canvas.configure(bg=bg)
        self._draw_icon(icon, bg)

    def _draw_icon(self, color: str, bg: str) -> None:
        self.canvas.delete("all")
        width, height = self.ratio
        max_w, max_h = 26, 18
        scale = min(max_w / width, max_h / height)
        rect_w = max(8, int(width * scale))
        rect_h = max(8, int(height * scale))
        x1 = (34 - rect_w) // 2
        y1 = (24 - rect_h) // 2
        self.canvas.create_rectangle(x1, y1, x1 + rect_w, y1 + rect_h, outline=color, width=2, fill=bg)


class ResultCanvas(ctk.CTkFrame):
    def __init__(self, master, app: ImageStudioApp) -> None:
        super().__init__(master, corner_radius=10)
        self.app = app
        self.palette: ThemePalette | None = None
        self._images: list[ctk.CTkImage] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.title = ctk.CTkLabel(self, text="生成结果", anchor="w", font=ctk.CTkFont(size=18, weight="bold"))
        self.title.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        self.body = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.body.grid_columnconfigure((0, 1), weight=1)
        self.show_empty()

    def apply_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.configure(fg_color=palette.panel, border_color=palette.border, border_width=1)
        self.title.configure(text_color=palette.text)
        self.body.configure(fg_color=palette.surface, border_color=palette.border, border_width=1)

    def clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self._images.clear()

    def show_empty(self, message: str = "还没有生成图片") -> None:
        self.clear()
        palette = self.palette or AppTheme.palettes["dark"]
        frame = ctk.CTkFrame(self.body, fg_color="transparent", height=520)
        frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=14, pady=14)
        frame.grid_propagate(False)
        ctk.CTkLabel(frame, text="+", font=ctk.CTkFont(size=54, weight="bold"), text_color=palette.muted).place(relx=0.5, rely=0.42, anchor="center")
        ctk.CTkLabel(frame, text=message, text_color=palette.muted).place(relx=0.5, rely=0.52, anchor="center")

    def show_loading(self) -> None:
        self.clear()
        palette = self.palette or AppTheme.palettes["dark"]
        frame = ctk.CTkFrame(self.body, fg_color="transparent", height=520)
        frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=14, pady=14)
        frame.grid_propagate(False)
        ctk.CTkLabel(frame, text="正在生成...", font=ctk.CTkFont(size=18, weight="bold"), text_color=palette.text).place(relx=0.5, rely=0.48, anchor="center")
        ctk.CTkLabel(frame, text="生成完成后会自动保存到本地", text_color=palette.muted).place(relx=0.5, rely=0.54, anchor="center")

    def show_images(self, paths: list[Path], prompt: str) -> None:
        self.clear()
        palette = self.palette or AppTheme.palettes["dark"]
        existing = [path for path in paths if path.exists()]
        if not existing:
            self.show_empty("图片文件不存在")
            return
        for index, path in enumerate(existing):
            image = Image.open(path)
            image.thumbnail((430, 430))
            ctk_image = ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=image.size)
            self._images.append(ctk_image)
            card = ctk.CTkFrame(self.body, corner_radius=8, fg_color=palette.panel_alt, border_color=palette.border, border_width=1)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=10, pady=10)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, image=ctk_image, text="").grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 8))
            name = ctk.CTkLabel(card, text=path.name, text_color=palette.muted, anchor="w")
            name.grid(row=1, column=0, sticky="ew", padx=10)
            tools = ctk.CTkFrame(card, fg_color="transparent")
            tools.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
            ctk.CTkButton(tools, text="打开目录", width=82, command=lambda p=path: self.app.open_parent_dir(p)).pack(side="left", padx=(0, 8))
            ctk.CTkButton(tools, text="添加为参考", width=96, command=lambda p=path: self.app.add_reference_from_result(p)).pack(side="left", padx=(0, 8))
            ctk.CTkButton(tools, text="复制路径", width=88, command=lambda p=path: self.app.copy_path(p)).pack(side="left", padx=(0, 8))
            ctk.CTkButton(tools, text="填回提示词", width=96, command=lambda value=prompt: self.app.parameters.set_prompt(value)).pack(side="left")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master: ImageStudioApp, store: ConfigStore, config: AppConfig, palette: ThemePalette, on_saved) -> None:
        super().__init__(master)
        self.title("设置")
        self.geometry("680x430")
        self.transient(master)
        self.grab_set()
        self.store = store
        self.config = config
        self.palette = palette
        self.on_saved = on_saved
        self.configure(fg_color=palette.bg)
        self.grid_columnconfigure(1, weight=1)

        self.output_var = ctk.StringVar(value=str(config.output_dir))

        ctk.CTkLabel(self, text="保存目录", text_color=palette.text).grid(row=0, column=0, sticky="w", padx=22, pady=18)
        entry = ctk.CTkEntry(self, textvariable=self.output_var, fg_color=palette.input, border_color=palette.border, text_color=palette.text)
        entry.grid(row=0, column=1, sticky="ew", padx=10, pady=18)
        ctk.CTkButton(self, text="选择", width=86, command=self._choose_dir).grid(row=0, column=2, padx=18, pady=18)

        self.status_var = ctk.StringVar(value="接口地址和 Key 已内置，设置页只保存图片目录。")
        ctk.CTkLabel(self, textvariable=self.status_var, text_color=palette.muted).grid(row=1, column=0, columnspan=3, sticky="ew", padx=22, pady=(4, 12))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=3, sticky="e", padx=22, pady=16)
        ctk.CTkButton(actions, text="保存", fg_color=palette.accent, hover_color=palette.accent_hover, command=self._save).pack(side="left", padx=8)

    def _choose_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()))
        if selected:
            self.output_var.set(selected)

    def _save(self) -> None:
        config = AppConfig(
            base_url=self.config.base_url,
            default_model=self.config.default_model,
            default_size=self.config.default_size,
            output_dir=Path(self.output_var.get()).expanduser(),
            theme=self.config.theme,
        )
        saved = self.store.save(config)
        self.on_saved(saved)
        self.destroy()


class HistoryDialog(ctk.CTkToplevel):
    def __init__(self, master: ImageStudioApp, store: HistoryStore, palette: ThemePalette, on_fill) -> None:
        super().__init__(master)
        self.app = master
        self.store = store
        self.title("历史记录")
        self.geometry("760x560")
        self.transient(master)
        self.grab_set()
        self.palette = palette
        self.on_fill = on_fill
        self._thumbs: list[ctk.CTkImage] = []
        self.configure(fg_color=palette.bg)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=16)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="历史记录", font=ctk.CTkFont(size=20, weight="bold"), text_color=palette.text).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="一键删除", width=92, fg_color=palette.danger, hover_color=palette.danger, command=self._clear_all).grid(row=0, column=1, sticky="e")
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=palette.panel, border_color=palette.border, border_width=1)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self._render_records()

    def _render_records(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._thumbs.clear()
        records = self.store.list_recent(80)
        if not records:
            ctk.CTkLabel(self.list_frame, text="还没有历史记录", text_color=self.palette.muted).pack(pady=40)
            return
        for record in records:
            self._add_record(self.list_frame, record)

    def _add_record(self, parent: ctk.CTkScrollableFrame, record: HistoryRecord) -> None:
        card = ctk.CTkFrame(parent, corner_radius=8, fg_color=self.palette.panel_alt, border_color=self.palette.border, border_width=1)
        card.pack(fill="x", padx=10, pady=8)
        card.grid_columnconfigure(1, weight=1)
        thumb_label = ctk.CTkLabel(card, text="", width=96, height=96)
        thumb_label.grid(row=0, column=0, rowspan=2, padx=10, pady=10)
        first_image = next((path for path in record.image_paths if path.exists()), None)
        if first_image:
            image = Image.open(first_image)
            image.thumbnail((96, 96))
            thumb = ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=image.size)
            self._thumbs.append(thumb)
            thumb_label.configure(image=thumb)
        else:
            thumb_label.configure(text="无图片", text_color=self.palette.muted)
        info = f"{record.created_at}  {record.model or '默认模型'}  {record.size}\n{record.prompt[:160]}"
        ctk.CTkLabel(card, text=info, anchor="w", justify="left", text_color=self.palette.text).grid(row=0, column=1, sticky="ew", padx=8, pady=(10, 4))
        tools = ctk.CTkFrame(card, fg_color="transparent")
        tools.grid(row=1, column=1, sticky="w", padx=8, pady=(0, 10))
        ctk.CTkButton(tools, text="填回", width=72, command=lambda r=record: self._fill(r)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(tools, text="打开目录", width=82, command=lambda p=first_image: self.app.open_parent_dir(p) if p else None).pack(side="left", padx=(0, 8))
        ctk.CTkButton(tools, text="复制提示词", width=96, command=lambda r=record: self._copy_prompt(r.prompt)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(tools, text="删除", width=70, fg_color=self.palette.danger, hover_color=self.palette.danger, command=lambda r=record: self._delete_record(r)).pack(side="left")

    def _fill(self, record: HistoryRecord) -> None:
        self.on_fill(record)
        self.destroy()

    def _copy_prompt(self, prompt: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(prompt)

    def _delete_record(self, record: HistoryRecord) -> None:
        if not messagebox.askyesno("删除历史", "确定删除这条历史记录吗？图片文件不会被删除。", parent=self):
            return
        self.store.delete(record.id)
        self._render_records()

    def _clear_all(self) -> None:
        if not messagebox.askyesno("一键删除", "确定删除全部历史记录吗？图片文件不会被删除。", parent=self):
            return
        self.store.clear()
        self._render_records()


def main() -> None:
    app = ImageStudioApp()
    app.mainloop()


def resource_path(name: str) -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / name
    return Path(__file__).resolve().parents[2] / name


if __name__ == "__main__":
    main()
