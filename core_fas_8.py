import math
import csv
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import tkinter.font as tkFont
import xml.sax.saxutils as saxutils

from PIL import Image  # pip install pillow


DEFAULT_FUEL_TYPES = [
    {"name": "Пусто",  "color": "#FFFFFF"},
    {"name": "Тип 1",  "color": "#FFCC00"},
    {"name": "Тип 2",  "color": "#66CCFF"},
    {"name": "Тип 3",  "color": "#FF6666"},
    {"name": "Тип 4",  "color": "#99CC00"},
    {"name": "Тип 5",  "color": "#CC99FF"},
    {"name": "Тип 6",  "color": "#FF9966"},
    {"name": "Тип 7",  "color": "#00CC99"},
    {"name": "Тип 8",  "color": "#9999FF"},
    {"name": "Тип 9",  "color": "#CCCCCC"},
    {"name": "Тип 10", "color": "#FFCCFF"},
]


class CoreMapGUI:
    def __init__(self, master, *, embedded: bool = False, integrated_mode: bool = False, on_calc_request=None):
        """
        embedded=True  -> не трогаем заголовок/геометрию окна (класс можно вставлять в ttk.Notebook вкладку)
        integrated_mode=True -> клик по ТВС открывает диалог "рассчитать/выгрузить", вместо редактирования CSV
        on_calc_request(cell:str, time_h:float) -> callback из основного GUI для запуска расчёта дозы
        """
        self.master = master
        self.embedded = embedded
        self.integrated_mode = integrated_mode
        self.on_calc_request = on_calc_request

        # энергетика/выгрузка
        self.energy_by_cell = {}          # pos_label -> W*hr
        self.unloaded_poslabels = set()   # set[str]

        if (not self.embedded) and hasattr(master, "title"):
            master.title("Картограмма активной зоны (гекса + круги)")

        # ---------- Геометрия окна и Canvas ----------
        screen_w = master.winfo_screenwidth()
        screen_h = master.winfo_screenheight()

        left_panel_width = 260
        right_panel_width = 280

        canvas_side = min(
            screen_w - left_panel_width - right_panel_width - 60,
            screen_h - 80
        )
        canvas_side = max(500, canvas_side)

        # В embedded-режиме берём "разумный" стартовый размер,
        # дальше подстроимся по <Configure> самого Canvas
        if self.embedded:
            self.canvas_width = 900
            self.canvas_height = 650
        else:
            self.canvas_width = int(canvas_side)
            self.canvas_height = int(canvas_side)

        if not self.embedded and hasattr(self.master, "geometry"):
            win_w = min(screen_w, self.canvas_width + left_panel_width + right_panel_width + 40)
            win_h = min(screen_h, self.canvas_height + 80)
            self.master.geometry(f"{win_w}x{win_h}")


        # ---------- Состояние отображения ----------
        self.zoom_factor = 1.0
        self.pan_offset = (0.0, 0.0)
        self.rotation_angle_deg = 0
        self.hex_size = 20
        self.base_hex_size = 20
        self.default_rings = 7

        # Ячейки: key = canvas_id, value = dict(...)
        self.cells = {}
        # Типы ТВС
        self.fuel_types = self.make_default_fuel_types()
        # Статистика по типам (количество)
        self.type_counts = {}
        # Строки легенды
        self.legend_rows = {}

        # Шрифты
        self.font_pos = None
        self.font_factory = None

        # Вспомогательные состояния
        self._drag_start = None

        # Управляющие переменные
        self.export_format_var = tk.StringVar(value="PNG")
        self.export_font_scale = tk.DoubleVar(value=1.4)
        self.click_mode_var = tk.IntVar(value=0)      # 0 — тип+№+массы, 1 — только №+массы
        self.current_fuel_var = tk.IntVar(value=1)    # текущий тип ТВС
        self.pipette_mode_var = tk.BooleanVar(value=False)  # режим пипетки

        # Режим окраски (для градиента)
        self.coloring_mode_var = tk.StringVar(value="По типам ТВС")

        # Текстовые поля для статистики масс по выбранному типу
        self.stats_text_fuel = tk.StringVar(value="m_топл: данных нет")
        self.stats_text_abs = tk.StringVar(value="m_погл: данных нет")

        # Поворот картограммы
        self.rotation_label_var = tk.StringVar(value="0°")

        # Tooltip
        self.tooltip_window = None
        self.tooltip_label = None
        self.tooltip_cell_id = None

        # Подсветка поиска
        self.highlighted_cells = set()

        self._build_widgets()
        self.build_default_full_lattice()
        self.update_fuel_type_combo()
        self.build_legend()
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()

    # ---------- Типы ТВС ----------

    @staticmethod
    def make_default_fuel_types():
        return [dict(ft) for ft in DEFAULT_FUEL_TYPES]

    @staticmethod
    def _auto_color_for_index(idx: int) -> str:
        if idx == 0:
            return "#FFFFFF"
        palette = [
            "#FFCC00", "#66CCFF", "#FF6666", "#99CC00",
            "#CC99FF", "#FF9966", "#00CC99", "#9999FF",
            "#CCCCCC", "#FFCCFF",
        ]
        return palette[(idx - 1) % len(palette)]

    def get_or_create_fuel_type_index(self, type_label: str) -> int:
        """
        Преобразует текстовый ярлык типа ТВС (например, 'ОМ-1' или 'ПЗ-2')
        во внутренний индекс fuel_type. Если такого типа ещё нет в self.fuel_types,
        он создаётся с автоматически подобранным цветом.

        Поддерживает старый формат, когда в CSV в fuel_type записывался просто индекс.
        """
        if type_label is None:
            type_label = ""
        name = str(type_label).strip()

        # Пустое поле считаем "Пусто"
        if not name:
            name = "Пусто"

        # СТАРЫЙ ФОРМАТ: если поле целочисленное — трактуем его как индекс
        if name.isdigit():
            idx = int(name)
            # расширяем список типов до нужного индекса
            while len(self.fuel_types) <= idx:
                j = len(self.fuel_types)
                self.fuel_types.append({
                    "name": f"Тип {j}",
                    "color": self._auto_color_for_index(j),
                })
            return idx

        # НОВЫЙ ФОРМАТ: строковое имя типа ('ОМ-1', 'ПЗ-2', ...)
        # ищем существующий тип с таким именем
        for idx, ft in enumerate(self.fuel_types):
            if ft["name"] == name:
                return idx

        # если не нашли — создаём новый тип
        new_idx = len(self.fuel_types)
        self.fuel_types.append({
            "name": name,
            "color": self._auto_color_for_index(new_idx),
        })
        return new_idx


    def reset_default_fuel_types(self):
        self.fuel_types = self.make_default_fuel_types()

    # ---------- UI ----------

    def _build_widgets(self):
        main_frame = ttk.Frame(self.master)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # -------- Левая панель: легенда типов ТВС --------
        legend_panel = ttk.Frame(main_frame)
        legend_panel.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)

        ttk.Label(legend_panel, text="Типы ТВС").pack(anchor="w")
        self.legend_list_frame = ttk.Frame(legend_panel)
        self.legend_list_frame.pack(anchor="w", fill="x", pady=(2, 5))

        ttk.Button(
            legend_panel,
            text="Добавить тип",
            command=self.add_new_type
        ).pack(anchor="w", pady=(5, 0))

        # -------- Центральная область: Canvas --------
        self.canvas = tk.Canvas(
            main_frame,
            width=self.canvas_width,
            height=self.canvas_height,
            bg="white"
        )
        self.canvas.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        # -------- Правая панель: управление (прокручиваемая) --------
        control_container = ttk.Frame(main_frame)
        control_container.grid(row=0, column=2, sticky="ns", padx=5, pady=5)

        self.control_canvas = tk.Canvas(
            control_container,
            highlightthickness=0
        )
        control_scrollbar = ttk.Scrollbar(
            control_container,
            orient="vertical",
            command=self.control_canvas.yview
        )

        self.control_canvas.grid(row=0, column=0, sticky="ns")
        control_scrollbar.grid(row=0, column=1, sticky="ns")

        control_container.rowconfigure(0, weight=1)
        control_container.columnconfigure(0, weight=1)

        self.control_canvas.configure(yscrollcommand=control_scrollbar.set)

        control = ttk.Frame(self.control_canvas)
        self.control_canvas.create_window(
            (0, 0),
            window=control,
            anchor="nw",
            tags=("control_window",)
        )

        def _on_control_frame_configure(event):
            self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all"))
            self.control_canvas.itemconfig(
                "control_window",
                width=self.control_canvas.winfo_width()
            )

        control.bind("<Configure>", _on_control_frame_configure)
        self.control_canvas.bind("<MouseWheel>", self.on_control_mousewheel)

        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # --- Выбор текущего типа ТВС ---
        ttk.Label(control, text="Текущий тип ТВС:").pack(anchor="w")
        self.fuel_combo = ttk.Combobox(
            control,
            state="readonly",
            width=20
        )
        self.fuel_combo.pack(anchor="w", pady=(0, 10))

        def on_fuel_select(event):
            idx = self.fuel_combo.current()
            if idx >= 0:
                self.current_fuel_var.set(idx)
                self.apply_coloring_mode()
                self.update_mass_stats_for_selected_type()

        self.fuel_combo.bind("<<ComboboxSelected>>", on_fuel_select)

        # --- Загрузка/сохранение CSV ---
        ttk.Button(
            control,
            text="Загрузить картограмму (CSV)",
            command=self.load_from_csv
        ).pack(fill="x", pady=2)

        ttk.Button(
            control,
            text="Сохранить картограмму (CSV)",
            command=self.save_to_csv
        ).pack(fill="x", pady=2)

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Построение полной решётки ---
        ttk.Label(control, text="Если CSV нет:").pack(anchor="w")
        ttk.Label(control, text="Число колец полной\nрешётки:").pack(anchor="w")

        self.rings_var = tk.IntVar(value=self.default_rings)
        ttk.Spinbox(
            control,
            from_=1,
            to=15,
            textvariable=self.rings_var,
            width=5
        ).pack(anchor="w", pady=(0, 5))

        ttk.Button(
            control,
            text="Построить полную решётку",
            command=self.build_default_full_lattice
        ).pack(fill="x", pady=(0, 10))

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Параметры экспорта ---
        ttk.Label(control, text="Формат экспорта:").pack(anchor="w")
        self.export_format_combo = ttk.Combobox(
            control,
            textvariable=self.export_format_var,
            values=["PNG", "TIFF", "JPEG", "SVG"],
            state="readonly",
            width=10
        )
        self.export_format_combo.pack(anchor="w", pady=(0, 5))

        ttk.Label(control, text="Коэфф. шрифта при экспорте:").pack(anchor="w")
        self.export_font_scale_spin = ttk.Spinbox(
            control,
            from_=0.5,
            to=3.0,
            increment=0.1,
            textvariable=self.export_font_scale,
            width=5
        )
        self.export_font_scale_spin.pack(anchor="w", pady=(0, 10))

        ttk.Button(
            control,
            text="Экспорт изображения",
            command=self.export_image
        ).pack(fill="x", pady=(0, 10))

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Режим окраски (градиент) ---
        ttk.Label(control, text="Режим окраски картограммы:").pack(anchor="w")
        color_modes = [
            "По типам ТВС",
            "Градиент m_топл (все)",
            "Градиент m_бор (все)",
            "Градиент m_гадолиний (все)",
            "Градиент m_топл (выбранный тип)",
            "Градиент m_бор (выбранный тип)",
            "Градиент m_гадолиний (выбранный тип)",
            "Градиент энерговыработка (W·h)",
            "Градиент энерговыработка (W*hr)",
        ]
        self.color_mode_combo = ttk.Combobox(
            control,
            textvariable=self.coloring_mode_var,
            values=color_modes,
            state="readonly",
            width=30
        )
        self.color_mode_combo.pack(anchor="w", pady=(0, 4))

        def on_color_mode_change(event):
            self.apply_coloring_mode()
            self.update_mass_stats_for_selected_type()

        self.color_mode_combo.bind("<<ComboboxSelected>>", on_color_mode_change)

        # --- Статистика по массам для выбранного типа ---
        ttk.Label(
            control,
            text="Статистика по массам\n(выбранный тип):"
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(
            control,
            textvariable=self.stats_text_fuel,
            wraplength=260,
            justify="left"
        ).pack(anchor="w")

        ttk.Label(
            control,
            textvariable=self.stats_text_abs,
            wraplength=260,
            justify="left"
        ).pack(anchor="w", pady=(0, 4))

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Режим клика + пипетка ---
        ttk.Label(control, text="Режим клика по ячейке:").pack(anchor="w")

        rb_frame = ttk.Frame(control)
        rb_frame.pack(anchor="w", pady=(2, 4))
        ttk.Radiobutton(
            rb_frame,
            text="Тип ТВС + заводской №,\nмассы топлива и поглотителей",
            variable=self.click_mode_var,
            value=0
        ).pack(anchor="w")
        ttk.Radiobutton(
            rb_frame,
            text="Только заводской № и массы\n(тип не менять)",
            variable=self.click_mode_var,
            value=1
        ).pack(anchor="w")

        ttk.Checkbutton(
            control,
            text="Пипетка (копировать тип ТВС)",
            variable=self.pipette_mode_var
        ).pack(anchor="w", pady=(4, 8))

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Поиск ---
        ttk.Label(control, text="Поиск ячейки:").pack(anchor="w")
        self.search_entry = ttk.Entry(control, width=18)
        self.search_entry.pack(anchor="w", pady=(0, 2))

        search_btn_frame = ttk.Frame(control)
        search_btn_frame.pack(anchor="w", pady=(0, 8))
        ttk.Button(
            search_btn_frame,
            text="По позиции",
            command=self.search_by_pos
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            search_btn_frame,
            text="По зав. номеру",
            command=self.search_by_factory
        ).pack(side="left")

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Поворот картограммы ---
        ttk.Label(control, text="Поворот картограммы:").pack(anchor="w")
        rotate_frame = ttk.Frame(control)
        rotate_frame.pack(anchor="w", pady=(2, 6))

        ttk.Button(
            rotate_frame,
            text="⟲ -30°",
            command=lambda: self.rotate_cartogram(-30)
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            rotate_frame,
            text="⟳ +30°",
            command=lambda: self.rotate_cartogram(30)
        ).pack(side="left", padx=(0, 4))

        ttk.Label(
            rotate_frame,
            textvariable=self.rotation_label_var
        ).pack(side="left")

        ttk.Button(
            control,
            text="Сбросить масштаб/сдвиг",
            command=self.reset_view
        ).pack(anchor="w", pady=(0, 4))

        ttk.Button(
            control,
            text="Сбросить поворот",
            command=self.reset_rotation
        ).pack(anchor="w", pady=(0, 6))

        ttk.Separator(control, orient=tk.HORIZONTAL).pack(fill="x", pady=5)

        # --- Подсказка по управлению ---
        ttk.Label(
            control,
            text=(
                "Управление:\n"
                "ЛКМ по ячейке –\n"
                "  в зависимости от\n"
                "  режима клика/пипетки\n"
                "Колесо мыши – зум (по картограмме)\n"
                "ПКМ + движение – сдвиг\n\n"
                "В ячейке:\n"
                "верх — метка позиции\n"
                "низ  — заводской №"
            )
        ).pack(anchor="w")

        # --- обработчики Canvas ---
        self.canvas.tag_bind("cell", "<Button-1>", self.on_cell_click)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<ButtonPress-3>", self.on_drag_start)
        self.canvas.bind("<B3-Motion>", self.on_drag_move)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", self.on_canvas_leave)

    def update_fuel_type_combo(self):
        values = [f"{i}: {ft['name']}" for i, ft in enumerate(self.fuel_types)]
        self.fuel_combo["values"] = values
        cur = self.current_fuel_var.get()
        if not values:
            return
        if cur >= len(self.fuel_types) or cur < 0:
            cur = 0
            self.current_fuel_var.set(cur)
        self.fuel_combo.current(cur)

    # ---------- Легенда слева ----------

    def build_legend(self):
        for w in self.legend_list_frame.winfo_children():
            w.destroy()
        self.legend_rows = {}

        for type_id, ft in enumerate(self.fuel_types):
            row = ttk.Frame(self.legend_list_frame)
            row.pack(anchor="w", pady=1, fill="x")

            color_label = tk.Label(
                row,
                width=2,
                height=1,
                bg=ft["color"],
                relief="solid",
                bd=1
            )
            color_label.pack(side="left", padx=(0, 4))
            color_label.bind(
                "<Button-1>",
                lambda e, tid=type_id: self.choose_color_for_type(tid)
            )

            name_var = tk.StringVar(value=f"{type_id}: {ft['name']}")
            ttk.Label(row, textvariable=name_var).pack(side="left")

            count_label = ttk.Label(row, text=str(self.type_counts.get(type_id, 0)))
            count_label.pack(side="right")

            self.legend_rows[type_id] = {
                "frame": row,
                "color_label": color_label,
                "name_var": name_var,
                "count_label": count_label,
            }

    def choose_color_for_type(self, type_id: int):
        if not (0 <= type_id < len(self.fuel_types)):
            return
        current_color = self.fuel_types[type_id]["color"]
        rgb, hex_color = colorchooser.askcolor(
            title=f"Цвет для типа {type_id}",
            initialcolor=current_color,
            parent=self.master
        )
        if not hex_color:
            return

        self.fuel_types[type_id]["color"] = hex_color

        row = self.legend_rows.get(type_id)
        if row:
            row["color_label"].config(bg=hex_color)

        # Если режим окраски "по типам" — сразу обновить картограмму
        if self.coloring_mode_var.get() == "По типам ТВС":
            for canvas_id, cell in self.cells.items():
                if cell["fuel_type"] == type_id:
                    self.canvas.itemconfig(canvas_id, fill=hex_color)

    def add_new_type(self):
        new_id = len(self.fuel_types)
        name = simpledialog.askstring(
            "Новый тип ТВС",
            "Введите название нового типа:",
            initialvalue=f"Тип {new_id}",
            parent=self.master
        )
        if name is None:
            return

        rgb, hex_color = colorchooser.askcolor(
            title="Цвет нового типа",
            initialcolor=self._auto_color_for_index(new_id),
            parent=self.master
        )
        if not hex_color:
            hex_color = self._auto_color_for_index(new_id)

        self.fuel_types.append({"name": name, "color": hex_color})
        self.recalculate_type_stats()
        self.build_legend()
        self.update_fuel_type_combo()
        self.current_fuel_var.set(new_id)
        self.fuel_combo.current(new_id)
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()

    # ---------- Геометрия гекса ----------

    @staticmethod
    def axial_to_pixel(q, r, size):
        x = size * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
        y = size * (1.5 * r)
        return x, y

    @staticmethod
    def hex_polygon_points(cx, cy, size):
        points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            x = cx + size * math.cos(angle)
            y = cy + size * math.sin(angle)
            points.extend([x, y])
        return points

    # ---------- Генерация полной решётки ----------

    def generate_full_axial_coords(self, rings):
        result = []
        radius = rings - 1
        for q in range(-radius, radius + 1):
            for r in range(-radius, radius + 1):
                s = -q - r
                if abs(s) <= radius:
                    result.append((q, r))
        result.sort(
            key=lambda qr: (
                abs(qr[0]) + abs(qr[1]) + abs(-qr[0] - qr[1]),
                qr[1],
                qr[0],
            )
        )
        return result

    def build_default_full_lattice(self):
        rings = int(self.rings_var.get())
        axial_coords = self.generate_full_axial_coords(rings)

        self.zoom_factor = 1.0
        self.pan_offset = (0.0, 0.0)
        self.rotation_angle_deg = 0
        self.update_rotation_label()
        self.reset_default_fuel_types()

        cells_data = []
        for idx, (q, r) in enumerate(axial_coords, start=1):
            pos_label = str(idx)
            cells_data.append({
                "index": idx,
                "q": q,
                "r": r,
                "shape": "hex",
                "fuel_type": 0,
                "pos_label": pos_label,
                "factory_id": "",
                "mass_fuel": "",
                "mass_boron": "",
                "mass_gd": "",
            })

        self.build_from_cells_data(cells_data)
        self.update_fuel_type_combo()
        self.build_legend()
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()

    # ---------- Построение по списку ячеек ----------

    def build_from_cells_data(self, cells_data):
        self.canvas.delete("all")
        self.cells.clear()
        self.highlighted_cells.clear()

        if not cells_data:
            return

        max_type = max(int(c["fuel_type"]) for c in cells_data)
        while max_type >= len(self.fuel_types):
            idx = len(self.fuel_types)
            self.fuel_types.append({
                "name": f"Тип {idx}",
                "color": self._auto_color_for_index(idx)
            })

        angle_rad = math.radians(self.rotation_angle_deg % 360)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        raw_positions = []
        for cell in cells_data:
            x_raw, y_raw = self.axial_to_pixel(cell["q"], cell["r"], 1.0)
            x_rot = x_raw * cos_a - y_raw * sin_a
            y_rot = x_raw * sin_a + y_raw * cos_a
            raw_positions.append((x_rot, y_rot))

        xs = [p[0] for p in raw_positions]
        ys = [p[1] for p in raw_positions]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        width_centers_raw = max_x - min_x
        height_centers_raw = max_y - min_y

        hex_margin_raw = 1.2
        width_raw = width_centers_raw + 2 * hex_margin_raw
        height_raw = height_centers_raw + 2 * hex_margin_raw

        pixel_margin = 20
        available_width = self.canvas_width - 2 * pixel_margin
        available_height = self.canvas_height - 2 * pixel_margin

        scale_x = available_width / width_raw
        scale_y = available_height / height_raw

        self.base_hex_size = min(scale_x, scale_y)
        self.hex_size = self.base_hex_size * self.zoom_factor

        pos_size = max(6, int(self.hex_size * 0.35))
        factory_size = max(5, int(self.hex_size * 0.28))
        self.font_pos = tkFont.Font(family="Arial", size=pos_size, weight="bold")
        self.font_factory = tkFont.Font(family="Arial", size=factory_size)

        center_raw_x = (min_x + max_x) / 2.0
        center_raw_y = (min_y + max_y) / 2.0

        canvas_center_x = self.canvas_width / 2.0
        canvas_center_y = self.canvas_height / 2.0

        pan_x, pan_y = self.pan_offset

        for cell, (x_raw, y_raw) in zip(cells_data, raw_positions):
            q = cell["q"]
            r = cell["r"]
            index = cell["index"]
            shape = cell.get("shape", "hex")
            fuel_type = int(cell.get("fuel_type", 0))
            pos_label = str(cell.get("pos_label", index))
            factory_id = str(cell.get("factory_id", ""))
            mass_fuel = str(cell.get("mass_fuel", ""))
            mass_boron = str(cell.get("mass_boron", ""))
            mass_gd = str(cell.get("mass_gd", ""))
            energy_wh = float(cell.get("energy_wh", 0.0) or 0.0)
            disabled = bool(cell.get("disabled", False))


            if fuel_type < 0 or fuel_type >= len(self.fuel_types):
                fuel_type = 0

            x = (x_raw - center_raw_x) * self.hex_size + canvas_center_x + pan_x
            y = (y_raw - center_raw_y) * self.hex_size + canvas_center_y + pan_y

            base_color = self.fuel_types[fuel_type]["color"]

            if shape == "circle":
                radius = self.hex_size * 0.72
                cell_id = self.canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    outline="black",
                    width=1,
                    fill=base_color,
                    tags=("cell",)
                )
            else:
                points = self.hex_polygon_points(x, y, self.hex_size * 0.9)
                cell_id = self.canvas.create_polygon(
                    points,
                    outline="black",
                    width=1,
                    fill=base_color,
                    tags=("cell",)
                )

            dy = self.hex_size * 0.25

            text_pos_id = self.canvas.create_text(
                x,
                y - dy,
                text=str(pos_label),
                font=self.font_pos
            )
            text_factory_id = self.canvas.create_text(
                x,
                y + dy,
                text=str(factory_id) if factory_id else "",
                font=self.font_factory
            )

            self.cells[cell_id] = {
                "index": index,
                "q": q,
                "r": r,
                "shape": shape,
                "fuel_type": fuel_type,
                "pos_label": pos_label,
                "factory_id": factory_id,
                "mass_fuel": mass_fuel,
                "mass_boron": mass_boron,
                "mass_gd": mass_gd,
                "text_pos_id": text_pos_id,
                "text_factory_id": text_factory_id,
                # интеграция с TVS_dose_2
                "disabled": False,
                "energy_wh": 0.0,   # W*hr
                "energy_wh": energy_wh,
                "disabled": disabled,
            }

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.tag_bind("cell", "<Button-1>", self.on_cell_click)

        self.recalculate_type_stats()
        self.build_legend()
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()

    def _rebuild_from_current_state(self):
        if not self.cells:
            return
        cells_data = []
        for cell in self.cells.values():
            cells_data.append({
                "index": cell["index"],
                "q": cell["q"],
                "r": cell["r"],
                "shape": cell["shape"],
                "fuel_type": cell["fuel_type"],
                "pos_label": cell.get("pos_label", str(cell["index"])),
                "factory_id": cell.get("factory_id", ""),
                "mass_fuel": cell.get("mass_fuel", ""),
                "mass_boron": cell.get("mass_boron", ""),
                "mass_gd": cell.get("mass_gd", ""),
                "energy_wh": cell.get("energy_wh", 0.0),
                "disabled": cell.get("disabled", False),
            })
        cells_data.sort(key=lambda c: c["index"])
        self.build_from_cells_data(cells_data)

    def recalculate_type_stats(self):
        self.type_counts = {i: 0 for i in range(len(self.fuel_types))}
        for cell in self.cells.values():
            t = cell.get("fuel_type", 0)
            if 0 <= t < len(self.fuel_types):
                self.type_counts[t] += 1
        for t, row in self.legend_rows.items():
            count = self.type_counts.get(t, 0)
            row["count_label"].config(text=str(count))

    # ---------- Подсветка поиска ----------

    def clear_highlight(self):
        for cid in self.highlighted_cells:
            if cid in self.cells:
                self.canvas.itemconfig(cid, outline="black", width=1)
        self.highlighted_cells.clear()

    def highlight_cells(self, cell_ids):
        self.clear_highlight()
        for cid in cell_ids:
            if cid in self.cells:
                self.canvas.itemconfig(cid, outline="red", width=3)
                self.highlighted_cells.add(cid)

    # ---------- Вспомогательные для масс и цветов ----------

    @staticmethod
    def _parse_mass(val) -> float:
        if val is None:
            return 0.0
        s = str(val).replace(",", ".").strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def _fmt_sci_1e(v: float) -> str:
        """
        Формат вида 1.1E-4 (без ведущих нулей в показателе).
        """
        try:
            v = float(v)
        except Exception:
            return ""
        if v == 0.0:
            return "0"
        s = f"{v:.1E}"          # например 1.2E-04
        mant, exp = s.split("E")
        exp_i = int(exp)        # -4
        return f"{mant}E{exp_i}".replace("E0", "E0")  # оставим как есть для exp=0


    @staticmethod
    def _interpolate_color(hex1: str, hex2: str, t: float) -> str:
        """Линейная интерполяция цвета между hex1 и hex2 при t ∈ [0,1]."""
        t = max(0.0, min(1.0, t))
        h1 = hex1.lstrip("#")
        h2 = hex2.lstrip("#")
        r1, g1, b1 = int(h1[0:2], 16), int(h1[2:4], 16), int(h1[4:6], 16)
        r2, g2, b2 = int(h2[0:2], 16), int(h2[2:4], 16), int(h2[4:6], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02X}{g:02X}{b:02X}"

    # ---------- Градиентная окраска ----------
    def apply_coloring_mode(self):
        """
        Применить выбранный режим окраски (по типам или градиент по массам).

        Градиент сделан по принципу VBA:
        - задаётся "центр" (здесь берем среднее по выбранной выборке);
        - отклонения вниз от центра -> холодные тона (R,G снижаются, B=255);
        - отклонения вверх -> тёплые (R=255, G,B снижаются);
        - при нулевом отклонении ячейка почти белая (R=G=B=255).
        Цвета не уходят в тёмные: компоненты ограничены диапазоном [100..255].
        """
        if not self.cells:
            return

        mode = self.coloring_mode_var.get()

        # Режим по типам ТВС — просто вернуть базовые цвета и заводские номера
        if mode == "По типам ТВС":
            for cid, cell in self.cells.items():
                if cell.get("disabled", False):
                    self.canvas.itemconfig(cid, fill="#FFFFFF", outline="#CCCCCC", width=1)
                    fact_text_id = cell.get("text_factory_id")
                    if fact_text_id:
                        self.canvas.itemconfig(fact_text_id, text="", fill="#CCCCCC", font=self.font_factory)
                    continue

                t = cell.get("fuel_type", 0)
                color = self.fuel_types[t]["color"] if 0 <= t < len(self.fuel_types) else "#FFFFFF"
                self.canvas.itemconfig(cid, fill=color, outline="black", width=1)

                fact_text_id = cell.get("text_factory_id")
                if fact_text_id:
                    self.canvas.itemconfig(
                        fact_text_id,
                        text=cell.get("factory_id", ""),
                        fill="black",
                        font=self.font_factory
                    )
            return

        if mode == "Градиент энерговыработка (W*hr)":
            # Собираем значения
            values = {}
            v_min = None
            v_max = None

            for cid, cell in self.cells.items():
                if cell.get("disabled", False):
                    continue
                v = float(cell.get("energy_wh", 0.0) or 0.0)
                if v <= 0.0:
                    continue
                values[cid] = v
                v_min = v if v_min is None else min(v_min, v)
                v_max = v if v_max is None else max(v_max, v)

            # Если нет данных — просто не мешаем (оставляем как есть)
            if not values:
                return

            # Простой градиент по min/max (стабильно и предсказуемо)
            span = (v_max - v_min) if (v_max is not None and v_min is not None) else 0.0
            if span <= 0.0:
                span = 1.0

            inactive_fill = "#F0F0F0"
            inactive_outline = "#CCCCCC"

            for cid, cell in self.cells.items():
                fact_text_id = cell.get("text_factory_id")

                if cell.get("disabled", False):
                    self.canvas.itemconfig(cid, fill="#FFFFFF", outline=inactive_outline, width=1)
                    if fact_text_id:
                        self.canvas.itemconfig(fact_text_id, text="", fill=inactive_outline, font=self.font_factory)
                    continue

                if cid in values:
                    v = values[cid]
                    t = (v - v_min) / span  # 0..1

                    # Цвет: от "холодного" к "тёплому" (можно заменить на вашу логику)
                    # Здесь используем интерполяцию между двумя цветами:
                    color = self._interpolate_color("#66CCFF", "#FF6666", t)

                    self.canvas.itemconfig(cid, fill=color, outline="black", width=1)
                    if fact_text_id:
                        self.canvas.itemconfig(
                            fact_text_id,
                            text=self._fmt_sci_1e(v),
                            fill="black",
                            font=self.font_factory,   # если нужно ещё компактнее — сделаем отдельный font_energy
                        )
                else:
                    self.canvas.itemconfig(cid, fill=inactive_fill, outline=inactive_outline, width=1)
                    if fact_text_id:
                        self.canvas.itemconfig(fact_text_id, text="", fill=inactive_outline, font=self.font_factory)

            return


        # Определение режима и области
        metric = None  # "fuel" | "boron" | "gd"
        per_type = False

        if mode == "Градиент m_топл (все)":
            metric = "fuel"
            per_type = False
        elif mode == "Градиент m_бор (все)":
            metric = "boron"
            per_type = False
        elif mode == "Градиент m_гадолиний (все)":
            metric = "gd"
            per_type = False
        elif mode == "Градиент m_топл (выбранный тип)":
            metric = "fuel"
            per_type = True
        elif mode == "Градиент m_бор (выбранный тип)":
            metric = "boron"
            per_type = True
        elif mode == "Градиент m_гадолиний (выбранный тип)":
            metric = "gd"
            per_type = True
        elif mode == "Градиент энерговыработка (W·h)":
            metric = "energy"
            per_type = False
        else:
            # неизвестный режим — вернуться к типам
            self.coloring_mode_var.set("По типам ТВС")
            self.color_mode_combo.set("По типам ТВС")
            self.apply_coloring_mode()
            return

        selected_type = self.current_fuel_var.get()

        # --- собираем значения и считаем min/max/mean ---
        values = {}  # cid -> v
        v_min = None
        v_max = None
        sum_v = 0.0

        for cid, cell in self.cells.items():
            if cell.get("disabled"):
                continue
            if per_type and cell.get("fuel_type") != selected_type:
                continue
            if metric == "fuel":
                v = self._parse_mass(cell.get("mass_fuel", ""))
            elif metric == "boron":
                v = self._parse_mass(cell.get("mass_boron", ""))
            elif metric == "energy":
                v = float(cell.get("energy_wh", 0.0) or 0.0)
            else:  # metric == "gd"
                v = self._parse_mass(cell.get("mass_gd", ""))

            # считаем только ненулевые значения
            if v <= 0.0:
                continue

            values[cid] = v
            sum_v += v
            if v_min is None or v < v_min:
                v_min = v
            if v_max is None or v > v_max:
                v_max = v

        if not values:
            messagebox.showinfo(
                "Градиентная окраска",
                "Нет ненулевых значений масс для выбранного режима.\n"
                "Режим окраски возвращён к типам ТВС."
            )
            self.coloring_mode_var.set("По типам ТВС")
            self.color_mode_combo.set("По типам ТВС")
            self.apply_coloring_mode()
            return

        # --- центр и "амплитуда" отклонений (аналог dblValueCenter / dblSwing) ---
        n_vals = len(values)
        center = sum_v / n_vals  # аналог dblValueCenter; в VBA он был 1.0, здесь — среднее

        # swing = max(|v_min - center|, |v_max - center|)
        swing = max(abs(v_min - center), abs(v_max - center))
        if swing <= 0.0:
            # все значения одинаковы – красим как почти белые для участвующих ячеек
            for cid, cell in self.cells.items():
                if per_type and cell.get("fuel_type") != selected_type:
                    # другие типы — белые
                    self.canvas.itemconfig(cid, fill="#FFFFFF", outline="black", width=1)
                else:
                    if cid in values:
                        self.canvas.itemconfig(cid, fill="#FFFFFF", outline="black", width=1)
                        fact_text_id = cell.get("text_factory_id")
                        if fact_text_id:
                            self.canvas.itemconfig(fact_text_id, text="+0.000", fill="black")
                    else:
                        # нулевые/отсутствующие – белые
                        self.canvas.itemconfig(cid, fill="#F0F0F0", outline="#CCCCCC", width=1)
                        fact_text_id = cell.get("text_factory_id")
                    if fact_text_id:
                        if metric == "energy":
                            self.canvas.itemconfig(fact_text_id, text=self._fmt_sci_1e(values[cid]), fill="black")
                        else:
                            self.canvas.itemconfig(fact_text_id, text="+0.000", fill="black")
            return

        # параметры цвета, как в VBA
        intColorMax = 255
        intColorMin = 100
        color_range = intColorMax - intColorMin

        # --- окраска ячеек ---
        inactive_fill = "#F0F0F0"
        inactive_outline = "#CCCCCC"
        for cid, cell in self.cells.items():
            if cell.get("disabled"):
                self.canvas.itemconfig(cid, fill="#FFFFFF", outline="black", width=1)
                fact_text_id = cell.get("text_factory_id")
                if fact_text_id:
                    self.canvas.itemconfig(fact_text_id, text="", fill="gray")
                continue

            if cid in values:
                v = values[cid]
                # нормированное отклонение от центра
                dev = abs(v - center) / swing  # 0..(примерно 1)
                if dev > 1.0:
                    dev = 1.0
                intDeltaColor = int(dev * color_range)

                if v < center:  # ниже центра — холодные тона (как ветка "value < center" в VBA)
                    intG = intColorMax - intDeltaColor
                    intB = intColorMax
                    intR = intColorMax - intDeltaColor
                elif v > center:  # выше центра — тёплые тона (как "value >= center" в VBA)
                    intR = intColorMax
                    intG = intColorMax - intDeltaColor
                    intB = intColorMax - intDeltaColor
                else:
                    intR = intColorMax
                    intG = intColorMax
                    intB = intColorMax

                color = f"#{intR:02X}{intG:02X}{intB:02X}"
                self.canvas.itemconfig(cid, fill=color, outline="black", width=1)

                # относительное отклонение от среднего (в долях)
                rel_dev = 0.0 if center == 0 else (v - center) / center
                fact_text_id = cell.get("text_factory_id")
                if fact_text_id:
                    if metric == "energy":
                        self.canvas.itemconfig(
                            fact_text_id,
                            text=self._fmt_sci_1e(v),
                            fill="black",
                        )
                    else:
                        self.canvas.itemconfig(
                            fact_text_id,
                            text=f"{rel_dev:+.3f}",
                            fill="black",
                        )


            else:
                # для ячеек без значения в текущем режиме:
                self.canvas.itemconfig(
                    cid,
                    fill=inactive_fill,
                    outline=inactive_outline,
                    width=1,
                )

                fact_text_id = cell.get("text_factory_id")
                if fact_text_id:
                    self.canvas.itemconfig(fact_text_id, text="", fill=inactive_outline)

    # ---------- Статистика масс по выбранному типу ----------

    def update_mass_stats_for_selected_type(self):
        """Пересчитать min/max/σ по массам для выбранного типа ТВС."""
        if not self.cells:
            self.stats_text_fuel.set("m_топл: данных нет")
            self.stats_text_abs.set("m_погл: данных нет")
            return

        t_sel = self.current_fuel_var.get()

        vals_fuel = []
        vals_abs = []  # m_B + m_Gd

        for cell in self.cells.values():
            if cell.get("fuel_type") != t_sel:
                continue

            mf = self._parse_mass(cell.get("mass_fuel", ""))
            mb = self._parse_mass(cell.get("mass_boron", ""))
            mg = self._parse_mass(cell.get("mass_gd", ""))
            ma = mb + mg

            if mf > 0.0:
                vals_fuel.append(mf)
            if ma > 0.0:
                vals_abs.append(ma)

        def format_stats(name: str, arr):
            if not arr:
                return f"{name}: данных нет"
            n = len(arr)
            vmin = min(arr)
            vmax = max(arr)
            mean = sum(arr) / n
            var = sum((x - mean) ** 2 for x in arr) / n
            sigma = var ** 0.5
            return (
                f"{name}: N={n}; "
                f"mean={mean:.5f}; "
                f"min={vmin:.5f}; max={vmax:.5f}; "
                f"σ={sigma:.5f}"
            )

        self.stats_text_fuel.set(format_stats("m_топл", vals_fuel))
        self.stats_text_abs.set(format_stats("m_погл", vals_abs))

    # ---------- Диалог редактирования ячейки ----------

    def edit_cell_dialog(self, cell):
        dlg = tk.Toplevel(self.master)
        dlg.title("Редактирование ячейки")
        dlg.transient(self.master)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Индекс: {cell['index']}").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        ttk.Label(dlg, text=f"Позиция: {cell.get('pos_label', cell['index'])}").grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        ttk.Label(dlg, text="Тип ТВС:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        type_values = [f"{i}: {ft['name']}" for i, ft in enumerate(self.fuel_types)]
        type_combo = ttk.Combobox(dlg, values=type_values, state="readonly", width=20)
        type_combo.grid(row=2, column=1, sticky="w", padx=5, pady=2)

        cell_type = cell.get("fuel_type", 0)
        selected_type = self.current_fuel_var.get()

        if self.click_mode_var.get() == 0:  # режим, где можно менять тип
            if 0 <= selected_type < len(self.fuel_types) and selected_type != cell_type:
                initial_type = selected_type
            else:
                initial_type = cell_type
        else:
            initial_type = cell_type

        if 0 <= initial_type < len(self.fuel_types):
            type_combo.current(initial_type)
        else:
            type_combo.current(0)

        if self.click_mode_var.get() == 1:
            type_combo.configure(state="disabled")

        ttk.Label(dlg, text="Заводской №:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
        factory_var = tk.StringVar(value=cell.get("factory_id", ""))
        factory_entry = ttk.Entry(dlg, textvariable=factory_var, width=22)
        factory_entry.grid(row=3, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(dlg, text="Масса топлива, кг:").grid(row=4, column=0, sticky="e", padx=5, pady=2)
        mass_fuel_var = tk.StringVar(value=cell.get("mass_fuel", ""))
        ttk.Entry(dlg, textvariable=mass_fuel_var, width=22).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(dlg, text="Масса бора, кг:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
        mass_boron_var = tk.StringVar(value=cell.get("mass_boron", ""))
        ttk.Entry(dlg, textvariable=mass_boron_var, width=22).grid(row=5, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(dlg, text="Масса гадолиния, кг:").grid(row=6, column=0, sticky="e", padx=5, pady=2)
        mass_gd_var = tk.StringVar(value=cell.get("mass_gd", ""))
        ttk.Entry(dlg, textvariable=mass_gd_var, width=22).grid(row=6, column=1, sticky="w", padx=5, pady=2)

        result = {}

        def on_ok():
            if self.click_mode_var.get() == 0:
                new_type_idx = type_combo.current()
                if new_type_idx < 0:
                    new_type_idx = cell["fuel_type"]
                result["fuel_type"] = new_type_idx
            else:
                result["fuel_type"] = cell["fuel_type"]

            result["factory_id"] = factory_var.get().strip()
            result["mass_fuel"] = mass_fuel_var.get().strip()
            result["mass_boron"] = mass_boron_var.get().strip()
            result["mass_gd"] = mass_gd_var.get().strip()
            dlg.destroy()

        def on_cancel():
            result.clear()
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.grid(row=7, column=0, columnspan=2, pady=5)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Отмена", command=on_cancel).pack(side="left", padx=5)

        factory_entry.focus_set()
        dlg.wait_window()

        return result if result else None

    # ---------- Клик по ячейке ----------

    def on_cell_click(self, event):
        current = self.canvas.find_withtag("current")
        if not current:
            return
        cell_id = current[0]
        cell = self.cells.get(cell_id)
        if not cell:
            return

        # --- интегрированный режим: клик = действия, а не редактирование CSV ---
        if getattr(self, "integrated_mode", False):
            self._action_cell_dialog(cell)
            return

        # Режим пипетки: только копирование типа
        if self.pipette_mode_var.get():
            fuel_idx = cell.get("fuel_type", 0)
            if 0 <= fuel_idx < len(self.fuel_types):
                self.current_fuel_var.set(fuel_idx)
                self.fuel_combo.current(fuel_idx)
            return

        # Обычный режим: диалог редактирования
        new_data = self.edit_cell_dialog(cell)
        if new_data is None:
            return

        old_type = cell["fuel_type"]
        new_type = new_data.get("fuel_type", old_type)
        if new_type < 0 or new_type >= len(self.fuel_types):
            new_type = old_type
        cell["fuel_type"] = new_type

        cell["factory_id"] = new_data.get("factory_id", cell.get("factory_id", ""))
        self.canvas.itemconfig(
            cell["text_factory_id"],
            text=cell["factory_id"] if cell["factory_id"] else ""
        )
        cell["mass_fuel"] = new_data.get("mass_fuel", cell.get("mass_fuel", ""))
        cell["mass_boron"] = new_data.get("mass_boron", cell.get("mass_boron", ""))
        cell["mass_gd"] = new_data.get("mass_gd", cell.get("mass_gd", ""))

        self.recalculate_type_stats()
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()

    # ---------- Масштабирование и панорамирование ----------

    def on_mouse_wheel(self, event):
        if event.delta > 0:
            self.zoom_factor *= 1.1
        else:
            self.zoom_factor *= 0.9

        self.zoom_factor = max(0.3, min(5.0, self.zoom_factor))
        self._rebuild_from_current_state()

    def on_control_mousewheel(self, event):
        """Прокрутка правой панели колесиком мыши."""
        self.control_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_drag_start(self, event):
        self._drag_start = (event.x, event.y)

    def on_drag_move(self, event):
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        dx = event.x - x0
        dy = event.y - y0
        self._drag_start = (event.x, event.y)

        px, py = self.pan_offset
        self.pan_offset = (px + dx, py + dy)
        self._rebuild_from_current_state()

    # ---------- Поворот картограммы ----------

    def update_rotation_label(self):
        self.rotation_label_var.set(f"{self.rotation_angle_deg % 360}°")

    def rotate_cartogram(self, delta_deg: int):
        self.rotation_angle_deg = (self.rotation_angle_deg + delta_deg) % 360
        self.update_rotation_label()
        self._rebuild_from_current_state()

    def reset_view(self):
        """Вернуть масштаб и сдвиг к значениям по умолчанию."""
        self.zoom_factor = 1.0
        self.pan_offset = (0.0, 0.0)
        self._rebuild_from_current_state()

    def reset_rotation(self):
        self.rotation_angle_deg = 0
        self.update_rotation_label()
        self._rebuild_from_current_state()

    # ---------- Всплывающая подсказка ----------

    def build_tooltip_text(self, cell):
        idx = cell["index"]
        pos = cell.get("pos_label", idx)
        q = cell.get("q")
        r = cell.get("r")
        ft = cell.get("fuel_type", 0)
        factory_id = cell.get("factory_id", "") or "—"
        mass_fuel = cell.get("mass_fuel", "") or "—"
        mass_boron = cell.get("mass_boron", "") or "—"
        mass_gd = cell.get("mass_gd", "") or "—"
        if 0 <= ft < len(self.fuel_types):
            ft_name = self.fuel_types[ft]["name"]
        else:
            ft_name = f"Тип {ft}"
        lines = [
            f"Индекс: {idx}",
            f"Позиция: {pos}",
            f"q, r: {q}, {r}",
            f"Тип ТВС: {ft} ({ft_name})",
            f"Зав. №: {factory_id}",
            f"m_топл: {mass_fuel}",
            f"m_B: {mass_boron}",
            f"m_Gd: {mass_gd}",
        ]
        return "\n".join(lines)

    def on_canvas_motion(self, event):
        ids = self.canvas.find_withtag("current")
        cell_id = None
        for cid in ids:
            if cid in self.cells:
                cell_id = cid
                break

        if cell_id is None:
            self.on_canvas_leave(event)
            return

        cell = self.cells[cell_id]
        text = self.build_tooltip_text(cell)

        x_root = self.canvas.winfo_rootx() + event.x + 15
        y_root = self.canvas.winfo_rooty() + event.y + 15

        if self.tooltip_window is None:
            tw = tk.Toplevel(self.master)
            tw.wm_overrideredirect(True)
            label = tk.Label(
                tw,
                text=text,
                bg="#ffffe0",
                justify="left",
                relief="solid",
                borderwidth=1,
                font=("Arial", 9)
            )
            label.pack(ipadx=2, ipady=2)
            self.tooltip_window = tw
            self.tooltip_label = label
        else:
            self.tooltip_label.config(text=text)
        self.tooltip_window.wm_geometry(f"+{x_root}+{y_root}")
        self.tooltip_cell_id = cell_id

    def on_canvas_leave(self, event):
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None
            self.tooltip_label = None
            self.tooltip_cell_id = None

    # ---------- Поиск ----------

    def search_by_pos(self):
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showinfo("Поиск", "Введите позицию (метка ячейки).")
            return
        matches = [cid for cid, cell in self.cells.items()
                   if str(cell.get("pos_label", "")) == query]
        if not matches and query.isdigit():
            idx = int(query)
            matches = [cid for cid, cell in self.cells.items()
                       if cell.get("index") == idx]
        if not matches:
            self.clear_highlight()
            messagebox.showinfo("Поиск", "Ячейки с такой позицией не найдено.")
            return
        self.highlight_cells(matches)
        messagebox.showinfo("Поиск", f"Найдено ячеек: {len(matches)}.")

    def search_by_factory(self):
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showinfo("Поиск", "Введите заводской номер.")
            return
        matches = [cid for cid, cell in self.cells.items()
                   if str(cell.get("factory_id", "")).strip() == query]
        if not matches:
            self.clear_highlight()
            messagebox.showinfo("Поиск", "Ячейки с таким заводским номером не найдено.")
            return
        self.highlight_cells(matches)
        messagebox.showinfo("Поиск", f"Найдено ячеек: {len(matches)}.")

    # ---------- Сохранение / загрузка CSV ----------

    def save_to_csv(self):
        if not self.cells:
            messagebox.showwarning("Сохранение", "Нет данных картограммы.")
            return

        filename = filedialog.asksaveasfilename(
            title="Сохранить картограмму в CSV",
            defaultextension=".csv",
            filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")]
        )
        if not filename:
            return

        entries = list(self.cells.values())
        entries.sort(key=lambda c: c["index"])

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(
                    [
                        "index", "q", "r", "shape", "fuel_type",
                        "pos_label", "factory_id",
                        "mass_fuel", "mass_boron", "mass_gd"
                    ]
                )
                for cell in entries:
                    ft_idx = cell.get("fuel_type", 0)
                    if 0 <= ft_idx < len(self.fuel_types):
                        ft_name = self.fuel_types[ft_idx]["name"]
                    else:
                        ft_name = ""

                    writer.writerow([
                        cell["index"],
                        cell["q"],
                        cell["r"],
                        cell["shape"],
                        ft_name,                      # пишем НАЗВАНИЕ типа ТВС
                        cell.get("pos_label", ""),
                        cell.get("factory_id", ""),
                        cell.get("mass_fuel", ""),
                        cell.get("mass_boron", ""),
                        cell.get("mass_gd", ""),
                    ])

            messagebox.showinfo("Сохранение", "Картограмма сохранена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить CSV:\n{e}")

    def load_from_csv(self):
        filename = filedialog.askopenfilename(
            title="Загрузить картограмму из CSV",
            filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")]
        )
        if not filename:
            return

        try:
            with open(filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter=";")
                rows = list(reader)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать CSV:\n{e}")
            return

        required = {"index", "q", "r", "shape", "fuel_type"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            messagebox.showerror(
                "Ошибка",
                "В CSV отсутствуют столбцы: " + ", ".join(missing)
            )
            return

        cells_data = []
        used_types = set()
        try:
            for row in rows:
                idx = int(row["index"])
                q = int(row["q"])
                r = int(row["r"])

                shape = row["shape"].strip().lower()
                if shape not in ("hex", "circle"):
                    shape = "hex"

                # читаем тип ТВС как текст и получаем для него внутренний индекс
                fuel_type_label = row.get("fuel_type", "")
                fuel_type = self.get_or_create_fuel_type_index(fuel_type_label)

                pos_label = row.get("pos_label") if "pos_label" in row else ""
                if not pos_label:
                    pos_label = str(idx)

                factory_id = row.get("factory_id") if "factory_id" in row else ""
                if factory_id is None:
                    factory_id = ""

                mass_fuel = row.get("mass_fuel") if "mass_fuel" in row else ""
                mass_boron = row.get("mass_boron") if "mass_boron" in row else ""
                mass_gd = row.get("mass_gd") if "mass_gd" in row else ""

                cells_data.append({
                    "index": idx,
                    "q": q,
                    "r": r,
                    "shape": shape,
                    "fuel_type": fuel_type,
                    "pos_label": pos_label,
                    "factory_id": factory_id,
                    "mass_fuel": mass_fuel,
                    "mass_boron": mass_boron,
                    "mass_gd": mass_gd,
                })
        except Exception as e:
            messagebox.showerror("Ошибка", f"Некорректный формат CSV:\n{e}")
            return

        if used_types:
            max_type = max(used_types)
        else:
            max_type = 0

        self.zoom_factor = 1.0
        self.pan_offset = (0.0, 0.0)
        self.rotation_angle_deg = 0
        self.update_rotation_label()

        self.build_from_cells_data(cells_data)
        self.update_fuel_type_combo()
        self.coloring_mode_var.set("По типам ТВС")
        self.color_mode_combo.set("По типам ТВС")
        self.apply_coloring_mode()
        self.update_mass_stats_for_selected_type()
        messagebox.showinfo("Загрузка", "Картограмма загружена.")

    # ---------- Экспорт изображений ----------

    def export_image(self):
        if not self.cells:
            messagebox.showwarning("Экспорт", "Нет данных для экспорта.")
            return

        fmt = self.export_format_var.get().upper()
        font_scale = float(self.export_font_scale.get())

        if fmt in ("PNG", "TIFF", "JPEG"):
            ext = fmt.lower() if fmt != "JPEG" else "jpg"
            filename = filedialog.asksaveasfilename(
                title=f"Экспорт в {fmt}",
                defaultextension=f".{ext}",
                filetypes=[(f"{fmt} изображения", f"*.{ext}"), ("Все файлы", "*.*")]
            )
            if not filename:
                return
            self._export_raster_via_eps(filename, fmt, font_scale)

        elif fmt == "SVG":
            filename = filedialog.asksaveasfilename(
                title="Экспорт в SVG",
                defaultextension=".svg",
                filetypes=[("SVG файлы", "*.svg"), ("Все файлы", "*.*")]
            )
            if not filename:
                return
            self._export_svg(filename, font_scale)
        else:
            messagebox.showerror("Экспорт", f"Формат {fmt} не поддерживается.")

    def _export_raster_via_eps(self, filename, fmt, font_scale):
        scale_for_eps = 4
        eps_file = os.path.splitext(filename)[0] + ".eps"

        old_pos_size = self.font_pos.cget("size") if self.font_pos else None
        old_factory_size = self.font_factory.cget("size") if self.font_factory else None

        try:
            if self.font_pos and old_pos_size is not None:
                self.font_pos.configure(size=int(old_pos_size * font_scale))
            if self.font_factory and old_factory_size is not None:
                self.font_factory.configure(size=int(old_factory_size * font_scale))

            self.canvas.update_idletasks()

            self.canvas.postscript(
                file=eps_file,
                colormode="color",
                pagewidth=self.canvas_width,
                pageheight=self.canvas_height
            )

            img = Image.open(eps_file)
            img.load(scale=scale_for_eps)

            if fmt == "JPEG":
                img = img.convert("RGB")
                img.save(filename, "JPEG", quality=95)
            elif fmt == "TIFF":
                img.save(filename, "TIFF")
            else:
                img.save(filename, "PNG")

            # os.remove(eps_file)

            messagebox.showinfo(
                "Экспорт",
                f"{fmt} успешно сохранён (повышенное разрешение, увеличенный шрифт)."
            )

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось экспортировать {fmt}:\n{e}")
        finally:
            if self.font_pos and old_pos_size is not None:
                self.font_pos.configure(size=old_pos_size)
            if self.font_factory and old_factory_size is not None:
                self.font_factory.configure(size=old_factory_size)
            self.canvas.update_idletasks()

    def _export_svg(self, filename, font_scale):
        width = self.canvas_width
        height = self.canvas_height

        pos_size = int(self.font_pos.cget("size") * font_scale) if self.font_pos else 10
        factory_size = int(self.font_factory.cget("size") * font_scale) if self.font_factory else 8

        def esc(text):
            return saxutils.escape(str(text))

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write(
                    f'<svg xmlns="http://www.w3.org/2000/svg" '
                    f'width="{width}" height="{height}" '
                    f'viewBox="0 0 {width} {height}">\n'
                )

                # Фигуры: берем текущий цвет fill у Canvas (учитывает градиент)
                for cell_id, cell in self.cells.items():
                    item_type = self.canvas.type(cell_id)
                    coords = self.canvas.coords(cell_id)
                    fill_color = self.canvas.itemcget(cell_id, "fill") or "#FFFFFF"
                    stroke_color = "#000000"

                    if item_type == "oval" and len(coords) == 4:
                        x1, y1, x2, y2 = coords
                        cx = (x1 + x2) / 2.0
                        cy = (y1 + y2) / 2.0
                        r = (min(x2 - x1, y2 - y1)) / 2.0
                        f.write(
                            f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
                            f'stroke="{stroke_color}" fill="{fill_color}"/>\n'
                        )
                    elif item_type == "polygon" and len(coords) >= 6:
                        points = " ".join(
                            f"{coords[i]:.2f},{coords[i+1]:.2f}"
                            for i in range(0, len(coords), 2)
                        )
                        f.write(
                            f'  <polygon points="{points}" '
                            f'stroke="{stroke_color}" fill="{fill_color}"/>\n'
                        )

                # Тексты
                for cell_id, cell in self.cells.items():
                    pos_text_id = cell.get("text_pos_id")
                    if pos_text_id:
                        x, y = self.canvas.coords(pos_text_id)
                        text = self.canvas.itemcget(pos_text_id, "text")
                        if text:
                            f.write(
                                f'  <text x="{x:.2f}" y="{y:.2f}" '
                                f'font-family="Arial" font-size="{pos_size}" '
                                f'text-anchor="middle" dominant-baseline="middle">'
                                f'{esc(text)}</text>\n'
                            )

                    fact_text_id = cell.get("text_factory_id")
                    if fact_text_id:
                        x, y = self.canvas.coords(fact_text_id)
                        text = self.canvas.itemcget(fact_text_id, "text")
                        if text:
                            f.write(
                                f'  <text x="{x:.2f}" y="{y:.2f}" '
                                f'font-family="Arial" font-size="{factory_size}" '
                                f'text-anchor="middle" dominant-baseline="middle">'
                                f'{esc(text)}</text>\n'
                            )

                f.write('</svg>\n')

            messagebox.showinfo("Экспорт", "SVG успешно сохранён.")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось экспортировать SVG:\n{e}")

    def load_from_csv_path(self, filename: str):
        """То же, что load_from_csv(), но без диалога выбора файла."""
        if not filename:
            return

        try:
            with open(filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter=";")
                rows = list(reader)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать CSV:\n{e}")
            return

        required = {"index", "q", "r", "shape", "fuel_type"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            messagebox.showerror("Ошибка", "В CSV отсутствуют столбцы: " + ", ".join(missing))
            return

        cells_data = []
        try:
            for row in rows:
                idx = int(row["index"])
                q = int(row["q"])
                r = int(row["r"])

                shape = row["shape"].strip().lower()
                if shape not in ("hex", "circle"):
                    shape = "hex"

                fuel_type_label = row.get("fuel_type", "")
                fuel_type = self.get_or_create_fuel_type_index(fuel_type_label)

                pos_label = row.get("pos_label") if "pos_label" in row else ""
                if not pos_label:
                    pos_label = str(idx)

                factory_id = row.get("factory_id") if "factory_id" in row else ""
                if factory_id is None:
                    factory_id = ""

                mass_fuel = row.get("mass_fuel") if "mass_fuel" in row else ""
                mass_boron = row.get("mass_boron") if "mass_boron" in row else ""
                mass_gd = row.get("mass_gd") if "mass_gd" in row else ""

                cells_data.append({
                    "index": idx,
                    "q": q,
                    "r": r,
                    "shape": shape,
                    "fuel_type": fuel_type,
                    "pos_label": pos_label,
                    "factory_id": factory_id,
                    "mass_fuel": mass_fuel,
                    "mass_boron": mass_boron,
                    "mass_gd": mass_gd,
                })
        except Exception as e:
            messagebox.showerror("Ошибка", f"Некорректный формат CSV:\n{e}")
            return

        self.zoom_factor = 1.0
        self.pan_offset = (0.0, 0.0)
        self.rotation_angle_deg = 0
        self.update_rotation_label()

        self.build_from_cells_data(cells_data)

    def set_energy_integrals(self, energy_by_cell: dict):
        """
        energy_by_cell: dict[pos_label -> W*hr]
        """
        self.energy_by_cell = dict(energy_by_cell or {})

        # проставим значения в ячейки
        for cid, cell in self.cells.items():
            pos = str(cell.get("pos_label", ""))
            cell["energy_wh"] = float(self.energy_by_cell.get(pos, 0.0) or 0.0)

        # переключаем режим окраски на энерговыработку
        self.coloring_mode_var.set("Градиент энерговыработка (W·h)")
        try:
            self.color_mode_combo.set("Градиент энерговыработка (W·h)")
        except Exception:
            pass

        self.apply_coloring_mode()

    def toggle_unloaded(self, pos_label: str):
        pos_label = str(pos_label)
        for cid, cell in self.cells.items():
            if str(cell.get("pos_label")) == pos_label:
                cell["disabled"] = not bool(cell.get("disabled", False))
                break
        self.apply_coloring_mode()

    def _action_cell_dialog(self, cell: dict):
        """
        Диалог по клику на ячейку в integrated_mode:
        - задать время
        - рассчитать дозу (callback)
        - выгрузить/вернуть ТВС (убрать заливку)
        """
        pos = str(cell.get("pos_label", ""))
        dlg = tk.Toplevel(self.canvas.winfo_toplevel())
        dlg.title(f"Ячейка {pos}")
        dlg.transient(self.canvas.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        w = float(cell.get("energy_wh", 0.0) or 0.0)
        disabled = bool(cell.get("disabled", False))

        ttk.Label(frm, text=f"Ячейка: {pos}").pack(anchor="w")
        ttk.Label(frm, text=f"Энерговыработка (W·h): {w:.6g}").pack(anchor="w", pady=(0, 8))

        time_var = tk.StringVar(value="0.08")
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="Время, ч:").pack(side="left")
        ttk.Entry(row, textvariable=time_var, width=12).pack(side="left", padx=(8, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        def run_calc():
            if self.on_calc_request is None:
                messagebox.showerror("Ошибка", "Не задан callback on_calc_request() из основного GUI.")
                return
            try:
                t_h = float(time_var.get().replace(",", "."))
            except Exception:
                messagebox.showerror("Ошибка", "Некорректное время (ч).")
                return
            dlg.destroy()
            self.on_calc_request(pos, t_h)

        def toggle():
            self.toggle_unloaded(pos)
            dlg.destroy()

        ttk.Button(btns, text="Рассчитать дозу", command=run_calc).pack(side="left")
        ttk.Button(
            btns,
            text=("Вернуть ТВС" if disabled else "Выгрузить ТВС"),
            command=toggle
        ).pack(side="left", padx=(10, 0))

        ttk.Button(btns, text="Закрыть", command=dlg.destroy).pack(side="right")


def main():
    root = tk.Tk()
    app = CoreMapGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
