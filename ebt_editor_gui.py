import json
import os
import shutil
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from bbt_level_tool import HEADER_SIZE, build_level_bytes, parse_level_bytes
from ebt_json_tool import export_ebt, import_ebt


def format_level_hex(level_bytes, level_width):
    header = level_bytes[:HEADER_SIZE]
    tiles = level_bytes[HEADER_SIZE:]

    lines = [
        "# Header",
        " ".join(f"{value:02X}" for value in header),
        "",
        f"# Tiles ({level_width} bytes per row)",
    ]

    for offset in range(0, len(tiles), level_width):
        row = tiles[offset:offset + level_width]
        lines.append(" ".join(f"{value:02X}" for value in row))

    return "\n".join(lines)


def parse_hex_text(text):
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned_lines.append(stripped)

    compact = "".join("".join(cleaned_lines).split())
    if not compact:
        raise ValueError("Hex editor is empty.")
    if len(compact) % 2 != 0:
        raise ValueError("Hex data must contain an even number of characters.")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError(f"Invalid hex data: {exc}") from exc


class EbtEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BattleBlock EBT Editor")
        self.root.geometry("1200x760")
        self.root.minsize(960, 640)

        self.current_ebt_path = None
        self.current_temp_dir = None
        self.current_manifest = None
        self.current_level_entry = None
        self.current_level_path = None
        self.current_level_data = None
        self.current_level_dirty = False
        self.suppress_modified_event = False

        self.playlist_var = tk.StringVar(value="No file opened")
        self.file_var = tk.StringVar(value="")
        self.level_info_var = tk.StringVar(value="Open an .ebt file to begin.")
        self.status_var = tk.StringVar(value="Ready.")
        self.selected_block_var = tk.StringVar(value="7")
        self.level_width_var = tk.StringVar(value="0")
        self.level_height_var = tk.StringVar(value="0")
        self.visual_assets_root = self._detect_visual_assets_root()
        self.visual_assets_var = tk.StringVar(
            value=self.visual_assets_root or "Visual assets not found"
        )
        self.block_sprite_paths = self._load_block_sprite_paths()
        self.base_block_photo_cache = {}
        self.block_photo_cache = {}
        self.visual_canvas_items = {}
        self.visual_cell_width = 25
        self.visual_cell_height = 20

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _detect_visual_assets_root(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(
                base_dir,
                "Battle-Block-Theater-Level-Editor-master",
            ),
            os.path.join(
                base_dir,
                "Battle-Block-Theater-Level-Editor-1.1.1",
            ),
        ]
        for path in candidates:
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "images.txt")):
                return path
        return None

    def _load_block_sprite_paths(self):
        if not self.visual_assets_root:
            return {}

        image_map_path = os.path.join(self.visual_assets_root, "images.txt")
        sprite_paths = {}
        try:
            with open(image_map_path, "r", encoding="utf-8") as file_obj:
                for line in file_obj:
                    line = line.strip()
                    if not line or "," not in line:
                        continue
                    hex_id, rel_path = line.split(",", 1)
                    rel_path = rel_path.strip()
                    if "blockSprites" not in rel_path:
                        continue
                    sprite_paths[int(hex_id, 16)] = os.path.join(self.visual_assets_root, rel_path)
        except OSError:
            return {}

        return sprite_paths

    def _get_base_block_photo(self, block_id):
        if block_id in self.base_block_photo_cache:
            return self.base_block_photo_cache[block_id]
        path = self.block_sprite_paths.get(block_id)
        if not path or not os.path.isfile(path):
            path = self.block_sprite_paths.get(256) or self.block_sprite_paths.get(0)
        if not path or not os.path.isfile(path):
            return None

        photo = tk.PhotoImage(file=path)
        self.base_block_photo_cache[block_id] = photo
        return photo

    def _get_block_photo(self, block_id, cell_w=None, cell_h=None):
        base_photo = self._get_base_block_photo(block_id)
        if base_photo is None:
            return None

        if cell_w is None or cell_h is None:
            return base_photo

        cache_key = (block_id, cell_w, cell_h)
        if cache_key in self.block_photo_cache:
            return self.block_photo_cache[cache_key]

        base_w = base_photo.width()
        base_h = base_photo.height()
        if cell_w == base_w and cell_h == base_h:
            self.block_photo_cache[cache_key] = base_photo
            return base_photo

        resized = base_photo.zoom(cell_w, cell_h).subsample(base_w, base_h)
        self.block_photo_cache[cache_key] = resized
        return resized

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(3, weight=1)

        ttk.Button(top, text="Open EBT", command=self.open_ebt).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(top, text="Save Level Hex", command=self.save_current_level).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(top, text="Save EBT As...", command=self.save_ebt_as).grid(row=0, column=2, padx=(0, 8))
        ttk.Label(top, textvariable=self.visual_assets_var, foreground="#555555").grid(row=0, column=3, sticky="e")

        header = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        header.grid(row=1, column=0, sticky="nsew")
        header.columnconfigure(1, weight=1)
        header.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(header, text="Levels", padding=8)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.level_tree = ttk.Treeview(left, columns=("size",), show="tree headings", height=24)
        self.level_tree.heading("#0", text="Level")
        self.level_tree.heading("size", text="Bytes")
        self.level_tree.column("#0", width=210, anchor="w")
        self.level_tree.column("size", width=80, anchor="e")
        self.level_tree.grid(row=0, column=0, sticky="nsew")
        self.level_tree.bind("<<TreeviewSelect>>", self.on_level_selected)

        tree_scroll = ttk.Scrollbar(left, orient="vertical", command=self.level_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.level_tree.configure(yscrollcommand=tree_scroll.set)

        right = ttk.LabelFrame(header, text="Editors", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, textvariable=self.playlist_var, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(right, textvariable=self.file_var, foreground="#555555").grid(row=0, column=1, sticky="e")

        self.editor_tabs = ttk.Notebook(right)
        self.editor_tabs.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        self.editor_tabs.bind("<<NotebookTabChanged>>", self.on_editor_tab_changed)

        hex_tab = ttk.Frame(self.editor_tabs)
        hex_tab.columnconfigure(0, weight=1)
        hex_tab.rowconfigure(0, weight=1)
        self.editor_tabs.add(hex_tab, text="Hex")

        self.hex_text = ScrolledText(
            hex_tab,
            wrap="none",
            undo=True,
            font=("Consolas", 10),
            padx=8,
            pady=8,
        )
        self.hex_text.grid(row=0, column=0, sticky="nsew")
        self.hex_text.bind("<<Modified>>", self.on_text_modified)

        visual_tab = ttk.Frame(self.editor_tabs, padding=8)
        visual_tab.columnconfigure(0, weight=1)
        visual_tab.rowconfigure(1, weight=1)
        self.editor_tabs.add(visual_tab, text="Visual")

        visual_toolbar = ttk.Frame(visual_tab)
        visual_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        visual_toolbar.columnconfigure(9, weight=1)

        ttk.Label(visual_toolbar, text="Block ID").grid(row=0, column=0, sticky="w")
        self.block_spinbox = tk.Spinbox(
            visual_toolbar,
            from_=0,
            to=255,
            textvariable=self.selected_block_var,
            width=6,
            command=self.update_selected_block_preview,
        )
        self.block_spinbox.grid(row=0, column=1, padx=(6, 8), sticky="w")
        self.block_spinbox.bind("<KeyRelease>", self.update_selected_block_preview)

        self.block_preview_label = ttk.Label(visual_toolbar, text="No preview", width=18)
        self.block_preview_label.grid(row=0, column=2, padx=(0, 12), sticky="w")

        ttk.Label(visual_toolbar, text="Width").grid(row=0, column=3, sticky="w")
        self.width_spinbox = tk.Spinbox(
            visual_toolbar,
            from_=1,
            to=255,
            textvariable=self.level_width_var,
            width=4,
        )
        self.width_spinbox.grid(row=0, column=4, padx=(6, 8), sticky="w")

        ttk.Label(visual_toolbar, text="Height").grid(row=0, column=5, sticky="w")
        self.height_spinbox = tk.Spinbox(
            visual_toolbar,
            from_=1,
            to=255,
            textvariable=self.level_height_var,
            width=4,
        )
        self.height_spinbox.grid(row=0, column=6, padx=(6, 8), sticky="w")

        ttk.Button(
            visual_toolbar,
            text="Resize Level",
            command=self.resize_level,
        ).grid(row=0, column=7, padx=(12, 0))

        ttk.Label(
            visual_toolbar,
            text="Left click places selected block. Right click erases.",
        ).grid(row=0, column=8, sticky="w")

        ttk.Button(
            visual_toolbar,
            text="Apply Hex To Visual",
            command=self.sync_visual_from_hex,
        ).grid(row=0, column=9, padx=(12, 0))

        visual_frame = ttk.Frame(visual_tab)
        visual_frame.grid(row=1, column=0, sticky="nsew")
        visual_frame.columnconfigure(0, weight=1)
        visual_frame.rowconfigure(0, weight=1)

        self.visual_canvas = tk.Canvas(visual_frame, background="#1f1f1f", highlightthickness=0)
        self.visual_canvas.grid(row=0, column=0, sticky="nsew")
        self.visual_canvas.bind("<Button-1>", self.on_visual_left_click)
        self.visual_canvas.bind("<Button-3>", self.on_visual_right_click)
        self.visual_canvas.bind("<Configure>", self.on_visual_canvas_configure)

        visual_y_scroll = ttk.Scrollbar(visual_frame, orient="vertical", command=self.visual_canvas.yview)
        visual_y_scroll.grid(row=0, column=1, sticky="ns")
        visual_x_scroll = ttk.Scrollbar(visual_frame, orient="horizontal", command=self.visual_canvas.xview)
        visual_x_scroll.grid(row=1, column=0, sticky="ew")
        self.visual_canvas.configure(
            yscrollcommand=visual_y_scroll.set,
            xscrollcommand=visual_x_scroll.set,
        )

        info = ttk.Frame(right)
        info.grid(row=2, column=0, columnspan=2, sticky="ew")
        info.columnconfigure(0, weight=1)

        ttk.Label(info, textvariable=self.level_info_var).grid(row=0, column=0, sticky="w")
        ttk.Button(info, text="Revert Level", command=self.reload_current_level).grid(row=0, column=1, padx=(8, 0))

        status = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Separator(status, orient="horizontal").grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(status, textvariable=self.status_var).grid(row=1, column=0, sticky="w")

    def set_status(self, text):
        self.status_var.set(text)

    def cleanup_temp_dir(self):
        if self.current_temp_dir and os.path.isdir(self.current_temp_dir):
            shutil.rmtree(self.current_temp_dir, ignore_errors=True)
        self.current_temp_dir = None

    def reset_editor_state(self):
        self.current_manifest = None
        self.current_level_entry = None
        self.current_level_path = None
        self.current_level_data = None
        self.current_level_dirty = False
        self.level_tree.delete(*self.level_tree.get_children())
        self.hex_text.delete("1.0", tk.END)
        self.visual_canvas.delete("all")
        self.visual_canvas_items.clear()
        self._clear_modified_flag()
        self.level_info_var.set("Open an .ebt file to begin.")

    def open_ebt(self):
        if not self._confirm_discard_unsaved():
            return

        path = filedialog.askopenfilename(
            title="Open EBT File",
            filetypes=[("BattleBlock EBT", "*.ebt"), ("All files", "*.*")],
        )
        if not path:
            return

        self.cleanup_temp_dir()
        self.reset_editor_state()

        self.current_temp_dir = tempfile.mkdtemp(prefix="bbt_ebt_editor_")

        try:
            export_ebt(path, self.current_temp_dir)
        except Exception as exc:
            self.cleanup_temp_dir()
            messagebox.showerror("Open Failed", str(exc))
            return

        manifest_path = os.path.join(self.current_temp_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as file_obj:
            self.current_manifest = json.load(file_obj)

        self.current_ebt_path = path
        self.playlist_var.set(f"Playlist: {self.current_manifest.get('playlist_name', '<unknown>')}")
        self.file_var.set(os.path.basename(path))

        level_entries = [entry for entry in self.current_manifest["entries"] if entry.get("kind") == "level"]
        for entry in level_entries:
            self.level_tree.insert("", "end", iid=str(entry["index"]), text=entry["name"], values=(entry["record_size"],))

        if level_entries:
            first_id = str(level_entries[0]["index"])
            self.level_tree.selection_set(first_id)
            self.level_tree.focus(first_id)
            self.on_level_selected()

        self.set_status(f"Opened {os.path.basename(path)} with {len(level_entries)} editable levels.")

    def _get_selected_entry(self):
        selection = self.level_tree.selection()
        if not selection or not self.current_manifest:
            return None
        selected_index = int(selection[0])
        for entry in self.current_manifest["entries"]:
            if entry.get("index") == selected_index and entry.get("kind") == "level":
                return entry
        return None

    def on_level_selected(self, event=None):
        new_entry = self._get_selected_entry()
        if not new_entry:
            return

        if self.current_level_entry and new_entry["index"] == self.current_level_entry["index"]:
            return

        if not self._confirm_switch_level():
            if self.current_level_entry:
                current_id = str(self.current_level_entry["index"])
                self.level_tree.selection_set(current_id)
                self.level_tree.focus(current_id)
            return

        self.current_level_entry = new_entry
        self.current_level_path = os.path.join(self.current_temp_dir, new_entry["json_file"])
        self.reload_current_level()

    def reload_current_level(self):
        if not self.current_level_path:
            return

        with open(self.current_level_path, "r", encoding="utf-8") as file_obj:
            self.current_level_data = json.load(file_obj)

        level_bytes = build_level_bytes(self.current_level_data)
        self._set_hex_text(format_level_hex(level_bytes, self.current_level_data["width"]))
        self.current_level_dirty = False
        self.render_visual_level()

        self.level_width_var.set(str(self.current_level_data["width"]))
        self.level_height_var.set(str(self.current_level_data["height"]))

        self.level_info_var.set(
            f"{self.current_level_entry['name']} | "
            f"{self.current_level_data['width']}x{self.current_level_data['height']} | "
            f"record size {self.current_level_entry['record_size']} bytes | "
            f"flag {self.current_level_entry['record_flag']} | "
            f"offset {self.current_level_entry['record_offset']}"
        )
        self.set_status(f"Loaded {self.current_level_entry['name']}.")
        self.update_selected_block_preview()

    def _set_hex_text(self, text):
        self.suppress_modified_event = True
        self.hex_text.delete("1.0", tk.END)
        self.hex_text.insert("1.0", text)
        self._clear_modified_flag()
        self.suppress_modified_event = False

    def render_visual_level(self):
        self.visual_canvas.delete("all")
        self.visual_canvas_items.clear()

        if not self.current_level_data:
            return

        width = int(self.current_level_data["width"])
        height = int(self.current_level_data["height"])
        tiles = self.current_level_data["tiles"]
        canvas_w = max(300, self.visual_canvas.winfo_width() - 4)
        canvas_h = max(200, self.visual_canvas.winfo_height() - 4)
        base_photo = self._get_base_block_photo(0) or self._get_base_block_photo(256)
        base_w = base_photo.width() if base_photo else 25
        base_h = base_photo.height() if base_photo else 20

        cell_w_by_width = max(1, canvas_w // max(1, width))
        cell_w_by_height = max(1, int((canvas_h / max(1, height)) * (base_w / base_h)))
        cell_w = max(8, min(base_w, cell_w_by_width, cell_w_by_height))
        cell_h = max(6, int(round(cell_w * (base_h / base_w))))
        self.visual_cell_width = cell_w
        self.visual_cell_height = cell_h

        for row_index in range(height):
            display_row = self._get_display_row_tiles(tiles[row_index])
            for col_index in range(width):
                block_id = int(display_row[col_index])
                x1 = col_index * cell_w
                y1 = row_index * cell_h
                x2 = x1 + cell_w
                y2 = y1 + cell_h
                photo = self._get_block_photo(block_id, cell_w, cell_h)
                if photo:
                    image_id = self.visual_canvas.create_image(x1, y1, anchor="nw", image=photo)
                else:
                    image_id = self.visual_canvas.create_rectangle(
                        x1, y1, x2, y2, fill="#444444", outline="#555555"
                    )
                    self.visual_canvas.create_text(
                        x1 + (cell_w / 2),
                        y1 + (cell_h / 2),
                        text=f"{block_id:02X}",
                        fill="white",
                    )
                border_id = self.visual_canvas.create_rectangle(
                    x1, y1, x2, y2, outline="#2b2b2b"
                )
                self.visual_canvas_items[(row_index, col_index)] = (image_id, border_id)

        self.visual_canvas.configure(
            scrollregion=(0, 0, width * cell_w, height * cell_h)
        )

    def _get_display_row_tiles(self, stored_row):
        # Visual display should map 1:1 to stored row columns.
        # The previous code shifted by one, causing all levels to appear offset.
        return stored_row

    def _visual_col_to_storage_col(self, visual_col, width):
        # Store and display use the same column indexing.
        return visual_col

    def update_selected_block_preview(self, event=None):
        try:
            block_id = max(0, min(255, int(self.selected_block_var.get())))
        except ValueError:
            return

        photo = self._get_block_photo(block_id)
        if photo:
            self.block_preview_label.configure(image=photo, text="")
            self.block_preview_label.image = photo
        else:
            self.block_preview_label.configure(image="", text=f"Block {block_id}")
            self.block_preview_label.image = None

    def on_visual_canvas_configure(self, event=None):
        if self.current_level_data:
            self.render_visual_level()

    def _sync_hex_from_level_data(self):
        if not self.current_level_data:
            return
        level_bytes = build_level_bytes(self.current_level_data)
        self._set_hex_text(format_level_hex(level_bytes, self.current_level_data["width"]))

    def sync_visual_from_hex(self):
        if not self.current_level_entry or not self.current_level_path:
            return False

        try:
            level_bytes = parse_hex_text(self.hex_text.get("1.0", tk.END))
            parsed_level = parse_level_bytes(level_bytes)
        except Exception as exc:
            messagebox.showerror("Invalid Level Hex", str(exc))
            return False

        # Update record_size if it changed
        actual_size = len(level_bytes)
        self.current_level_entry["record_size"] = actual_size
        parsed_level["record_size"] = actual_size

        parsed_level["name"] = self.current_level_entry["name"]
        parsed_level["record_flag"] = self.current_level_entry["record_flag"]
        parsed_level["record_offset"] = self.current_level_entry["record_offset"]
        self.current_level_data = parsed_level
        self.level_width_var.set(str(parsed_level["width"]))
        self.level_height_var.set(str(parsed_level["height"]))
        self.render_visual_level()
        return True

    def resize_level(self):
        if not self.current_level_data or not self.current_level_entry:
            messagebox.showerror("No Level Loaded", "Load a level first.")
            return

        try:
            new_width = int(self.level_width_var.get())
            new_height = int(self.level_height_var.get())
        except ValueError:
            messagebox.showerror("Invalid Dimensions", "Width and height must be positive integers.")
            return

        if new_width < 1 or new_height < 1 or new_width > 255 or new_height > 255:
            messagebox.showerror("Invalid Dimensions", "Width and height must be between 1 and 255.")
            return

        old_width = int(self.current_level_data["width"])
        old_height = int(self.current_level_data["height"])

        if new_width == old_width and new_height == old_height:
            return  # No change

        # Adjust tiles
        old_tiles = self.current_level_data["tiles"]
        new_tiles = []
        for row_idx in range(new_height):
            if row_idx < old_height:
                old_row = old_tiles[row_idx]
                if new_width <= old_width:
                    new_row = old_row[:new_width]
                else:
                    new_row = old_row + [0] * (new_width - old_width)
            else:
                new_row = [0] * new_width
            new_tiles.append(new_row)

        # Update level data
        self.current_level_data["width"] = new_width
        self.current_level_data["height"] = new_height
        self.current_level_data["tiles"] = new_tiles

        # Update header
        width_index = self.current_level_data["width_index"]
        height_index = self.current_level_data["height_index"]
        self.current_level_data["header_bytes"][width_index] = new_width
        self.current_level_data["header_bytes"][height_index] = new_height

        # Update record size
        new_record_size = 16 + new_width * new_height
        self.current_level_entry["record_size"] = new_record_size
        self.current_level_data["record_size"] = new_record_size

        # Save manifest
        manifest_path = os.path.join(self.current_temp_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as file_obj:
            json.dump(self.current_manifest, file_obj, indent=2)
            file_obj.write("\n")

        # Update UI
        self._sync_hex_from_level_data()
        self.current_level_dirty = True
        self.level_width_var.set(str(new_width))
        self.level_height_var.set(str(new_height))
        self.render_visual_level()

        self.level_info_var.set(
            f"{self.current_level_entry['name']} | "
            f"{new_width}x{new_height} | "
            f"record size {new_record_size} bytes | "
            f"flag {self.current_level_entry['record_flag']} | "
            f"offset {self.current_level_entry['record_offset']}"
        )
        self.set_status(f"Resized level to {new_width}x{new_height}.")

    def _paint_visual_tile(self, row_index, col_index, block_id):
        if not self.current_level_data:
            return

        width = int(self.current_level_data["width"])
        height = int(self.current_level_data["height"])
        if not (0 <= row_index < height and 0 <= col_index < width):
            return

        storage_col = self._visual_col_to_storage_col(col_index, width)
        self.current_level_data["tiles"][row_index][storage_col] = int(block_id)
        self._sync_hex_from_level_data()
        self.current_level_dirty = True
        self.render_visual_level()

    def _visual_coords_to_cell(self, event):
        if not self.current_level_data:
            return None

        x = self.visual_canvas.canvasx(event.x)
        y = self.visual_canvas.canvasy(event.y)
        col_index = int(x // self.visual_cell_width)
        row_index = int(y // self.visual_cell_height)
        width = int(self.current_level_data["width"])
        height = int(self.current_level_data["height"])

        if 0 <= row_index < height and 0 <= col_index < width:
            return row_index, col_index
        return None

    def on_visual_left_click(self, event):
        cell = self._visual_coords_to_cell(event)
        if not cell:
            return
        try:
            block_id = max(0, min(255, int(self.selected_block_var.get())))
        except ValueError:
            messagebox.showerror("Invalid Block ID", "Selected block ID must be a number from 0 to 255.")
            return
        self._paint_visual_tile(cell[0], cell[1], block_id)

    def on_visual_right_click(self, event):
        cell = self._visual_coords_to_cell(event)
        if not cell:
            return
        self._paint_visual_tile(cell[0], cell[1], 0)

    def _clear_modified_flag(self):
        self.hex_text.edit_modified(False)

    def on_text_modified(self, event=None):
        if self.suppress_modified_event:
            self._clear_modified_flag()
            return
        if self.hex_text.edit_modified():
            self.current_level_dirty = True
            self._clear_modified_flag()

    def save_current_level(self):
        if not self.current_level_entry or not self.current_level_path:
            messagebox.showinfo("No Level Selected", "Open an .ebt and select a level first.")
            return False

        try:
            level_bytes = parse_hex_text(self.hex_text.get("1.0", tk.END))
            parsed_level = parse_level_bytes(level_bytes)
        except Exception as exc:
            messagebox.showerror("Invalid Level Hex", str(exc))
            return False

        # Update record_size in case it changed
        actual_size = len(level_bytes)
        self.current_level_entry["record_size"] = actual_size
        parsed_level["record_size"] = actual_size

        parsed_level["name"] = self.current_level_entry["name"]
        parsed_level["record_flag"] = self.current_level_entry["record_flag"]
        parsed_level["record_offset"] = self.current_level_entry["record_offset"]

        with open(self.current_level_path, "w", encoding="utf-8") as file_obj:
            json.dump(parsed_level, file_obj, indent=2)
            file_obj.write("\n")

        # Save manifest with updated record_size
        manifest_path = os.path.join(self.current_temp_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as file_obj:
            json.dump(self.current_manifest, file_obj, indent=2)
            file_obj.write("\n")

        self.current_level_data = parsed_level
        self.current_level_dirty = False
        self.set_status(f"Saved level hex for {self.current_level_entry['name']}.")
        self.level_info_var.set(
            f"{self.current_level_entry['name']} | "
            f"{parsed_level['width']}x{parsed_level['height']} | "
            f"record size {actual_size} bytes | "
            f"flag {self.current_level_entry['record_flag']} | "
            f"offset {self.current_level_entry['record_offset']}"
        )
        self.render_visual_level()
        return True

    def on_editor_tab_changed(self, event=None):
        current_tab = self.editor_tabs.tab(self.editor_tabs.select(), "text")
        if current_tab == "Visual" and self.current_level_entry:
            self.sync_visual_from_hex()

    def save_ebt_as(self):
        if not self.current_manifest:
            messagebox.showinfo("No File Open", "Open an .ebt file first.")
            return

        if self.current_level_dirty and not self.save_current_level():
            return

        default_name = os.path.splitext(os.path.basename(self.current_ebt_path))[0] + "_edited.ebt"
        output_path = filedialog.asksaveasfilename(
            title="Save Rebuilt EBT",
            defaultextension=".ebt",
            initialfile=default_name,
            filetypes=[("BattleBlock EBT", "*.ebt"), ("All files", "*.*")],
        )
        if not output_path:
            return

        try:
            import_ebt(self.current_temp_dir, output_path, template_ebt=self.current_ebt_path)
        except Exception as exc:
            messagebox.showerror("Save Failed", str(exc))
            return

        self.set_status(f"Saved rebuilt .ebt to {output_path}")
        messagebox.showinfo("Saved", f"Rebuilt .ebt saved to:\n{output_path}")

    def _confirm_switch_level(self):
        if not self.current_level_dirty:
            return True

        choice = messagebox.askyesnocancel(
            "Unsaved Level Changes",
            "Save the current level hex before switching?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_current_level()
        return True

    def _confirm_discard_unsaved(self):
        if not self.current_level_dirty:
            return True
        choice = messagebox.askyesnocancel(
            "Unsaved Level Changes",
            "Save the current level hex before continuing?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_current_level()
        return True

    def on_close(self):
        if not self._confirm_discard_unsaved():
            return
        self.cleanup_temp_dir()
        self.root.destroy()


def main():
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    app = EbtEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
