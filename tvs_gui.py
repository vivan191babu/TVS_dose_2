# tvs_gui.py
# GUI для расчёта и визуализации результатов TVS_dose_2
# - Расчёт: InitStaticArray() + ProcessCell(cell, time_h)
# - Визуализация: построение графиков по уже готовым файлам Core_FAs/*.txt
#   1) Dose(t): 10 кривых "вплотную"
#   2) Profile(z): две кривые ("вплотную" и "40 см") для выбранного времени
#   3) Выбор плана испытаний

from __future__ import annotations

import os
import glob
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import Test_plan
import Chart

# Планирование и заглушка ТУК — опциональны (если модулей нет, GUI всё равно работает)
try:
    from planning import estimate_power_scale
    from tuk_stub import TUKStubParams
    _PLANNING_AVAILABLE = True
except Exception:
    _PLANNING_AVAILABLE = False


def read_core_fa_file(path: str):
    """
    Читает файл Core_FAs/<cell>.txt.
    Формат:
      col1: time[h]
      col2-11:  near  (10 точек по высоте)
      col12-21: far   (10 точек по высоте)

    Возвращает:
      times_h: list[float]
      near_10xT: list[list[float]]  (10 рядов)
      far_10xT : list[list[float]]  (10 рядов)
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Файл не найден: {path}")

    times = []
    near = [[] for _ in range(10)]
    far = [[] for _ in range(10)]

    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue

            parts = s.replace(",", ".").split()
            if len(parts) < 21:
                # иногда встречаются заголовки/пустые строки
                continue

            try:
                row = [float(x) for x in parts[:21]]
            except ValueError:
                continue

            t = row[0]
            times.append(t)
            for i in range(10):
                near[i].append(row[1 + i])
                far[i].append(row[11 + i])

    if not times:
        raise ValueError(f"Файл не содержит данных: {path}")

    return times, near, far


def closest_index(xs, x):
    best_i = 0
    best_d = abs(xs[0] - x)
    for i, v in enumerate(xs):
        d = abs(v - x)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


class TVSGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TVS_dose_2 — расчёт и визуализация")
        self.geometry("1250x720")

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.results_dir = os.path.join(self.base_dir, "Core_FAs")
        # ---- Test_Plan file (selected before init) ----
        default_plan = os.path.join(self.base_dir, "Configs", "Test_Plan.txt")
        self.test_plan_path = tk.StringVar(value=default_plan if os.path.isfile(default_plan) else "")


        # ---- calc inputs ----
        self.last_cell = tk.StringVar(value="1-1")
        self.last_time = tk.StringVar(value="10")
        self.last_output_file = tk.StringVar(value="")  # полный путь

        # ---- plot controls ----
        self.selected_result_name = tk.StringVar(value="")  # basename, напр. "1-1.txt"
        self.profile_t = tk.StringVar(value="10")

        # ---- planning controls ----
        self.plan_limit = tk.StringVar(value="1000")
        self.plan_tcheck = tk.StringVar(value="0")
        self.plan_safety = tk.StringVar(value="0.95")
        self.plan_crit = tk.StringVar(value="ALL_MAX")

        self.tuk_nfas = tk.StringVar(value="7")
        self.tuk_k_surf = tk.StringVar(value="0.08")
        self.tuk_k_1m = tk.StringVar(value="0.015")

        # ---- main notebook ----
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.tab_calc = ttk.Frame(self.nb)
        self.tab_plot = ttk.Frame(self.nb)

        self.nb.add(self.tab_calc, text="Расчёт")
        self.nb.add(self.tab_plot, text="Графики")

        self._build_calc_tab()
        self._build_plot_tab()

        # первичное заполнение списка файлов
        self.refresh_result_file_list()

    # ---------------- UI ----------------
    def _build_calc_tab(self):
        top = ttk.Frame(self.tab_calc, padding=10)
        top.pack(fill="x")

        plan_row = ttk.Frame(self.tab_calc, padding=(10, 0, 10, 10))
        plan_row.pack(fill="x")

        ttk.Label(plan_row, text="Файл Test_Plan:").pack(side="left")
        ttk.Entry(plan_row, width=90, textvariable=self.test_plan_path).pack(side="left", padx=8)
        ttk.Button(plan_row, text="Выбрать...", command=self.on_browse_test_plan).pack(side="left")


        ttk.Button(top, text="1) Инициализировать статику", command=self.on_init_static).pack(side="left")

        ttk.Label(top, text="   Ячейка:").pack(side="left", padx=(15, 3))
        ttk.Entry(top, width=10, textvariable=self.last_cell).pack(side="left")

        ttk.Label(top, text="Время, ч:").pack(side="left", padx=(10, 3))
        ttk.Entry(top, width=10, textvariable=self.last_time).pack(side="left")

        ttk.Button(top, text="2) Рассчитать", command=self.on_calc).pack(side="left", padx=(15, 0))

        mid = ttk.Frame(self.tab_calc, padding=10)
        mid.pack(fill="x")

        ttk.Label(mid, text="Выходной файл:").pack(side="left")
        ttk.Entry(mid, width=85, textvariable=self.last_output_file).pack(side="left", padx=8)

        ttk.Button(mid, text="Построить графики", command=self.refresh_plots).pack(side="left", padx=8)

        if _PLANNING_AVAILABLE:
            grp = ttk.LabelFrame(
                self.tab_calc,
                text="Планирование по дозовым ограничениям (оценка масштаба мощности)",
                padding=10
            )
            grp.pack(fill="x", padx=10, pady=10)

            row1 = ttk.Frame(grp)
            row1.pack(fill="x")
            ttk.Label(row1, text="Ограничение (ед. как в файле):").pack(side="left")
            ttk.Entry(row1, width=12, textvariable=self.plan_limit).pack(side="left", padx=6)

            ttk.Label(row1, text="t контроля, ч:").pack(side="left", padx=(10, 3))
            ttk.Entry(row1, width=8, textvariable=self.plan_tcheck).pack(side="left")

            ttk.Label(row1, text="коэф. запаса:").pack(side="left", padx=(10, 3))
            ttk.Entry(row1, width=8, textvariable=self.plan_safety).pack(side="left")

            row2 = ttk.Frame(grp)
            row2.pack(fill="x", pady=(8, 0))
            ttk.Label(row2, text="Критерий:").pack(side="left")
            ttk.Combobox(
                row2, width=18, textvariable=self.plan_crit, state="readonly",
                values=["TVS_NEAR_MAX", "TVS_FAR_MAX", "TUK_SURFACE", "TUK_1M", "ALL_MAX"]
            ).pack(side="left", padx=6)

            ttk.Label(row2, text="ТУК: N ТВС=").pack(side="left", padx=(10, 3))
            ttk.Entry(row2, width=6, textvariable=self.tuk_nfas).pack(side="left")

            ttk.Label(row2, text="k_пов=").pack(side="left", padx=(10, 3))
            ttk.Entry(row2, width=6, textvariable=self.tuk_k_surf).pack(side="left")

            ttk.Label(row2, text="k_1м=").pack(side="left", padx=(10, 3))
            ttk.Entry(row2, width=6, textvariable=self.tuk_k_1m).pack(side="left")

            ttk.Button(row2, text="Оценить коэффициент масштаба мощности", command=self.on_plan).pack(side="left", padx=12)

        self.log = tk.Text(self.tab_calc, height=18)
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_plot_tab(self):
        top = ttk.Frame(self.tab_plot, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Файл результата:").pack(side="left")

        self.cmb_files = ttk.Combobox(
            top,
            width=34,
            textvariable=self.selected_result_name,
            state="readonly",
        )
        self.cmb_files.pack(side="left", padx=6)
        self.cmb_files.bind("<<ComboboxSelected>>", self.on_combo_file_selected)

        ttk.Button(top, text="Обновить список", command=self.refresh_result_file_list).pack(side="left", padx=4)
        ttk.Button(top, text="Выбрать файл…", command=self.on_browse_result_file).pack(side="left", padx=4)
        ttk.Button(top, text="Построить", command=self.on_plot_selected_file).pack(side="left", padx=10)

        ttk.Label(top, text="   t для профиля (ч):").pack(side="left", padx=(20, 3))
        ttk.Entry(top, width=10, textvariable=self.profile_t).pack(side="left", padx=6)
        ttk.Button(top, text="Обновить профиль", command=self.refresh_profile_only).pack(side="left", padx=6)

        ttk.Label(top, text="   Текущий файл:").pack(side="left", padx=(20, 3))
        ttk.Label(top, textvariable=self.last_output_file).pack(side="left")

        self.nb_plot = ttk.Notebook(self.tab_plot)
        self.nb_plot.pack(fill="both", expand=True)

        self.tab_time = ttk.Frame(self.nb_plot)
        self.tab_prof = ttk.Frame(self.nb_plot)

        self.nb_plot.add(self.tab_time, text="Dose(t) — 10 точек (вплотную)")
        self.nb_plot.add(self.tab_prof, text="Profile(z) — вплотную/40 см")

        self.chart_time = Chart.ChartMainWindow(self.tab_time)
        self.chart_prof = Chart.ChartMainWindow(self.tab_prof)

    def _show_integrals_after_init(self, info):
        # Поддержка dict и tuple на случай несовпадения версий
        if isinstance(info, dict):
            print("DEBUG type(info) =", type(info))
            print("DEBUG info =", info)
            out_path = info["out_path"]

            cell_all = info["cell_all"]
            w_all = info["w_all"]
            w_2h_for_cell_all = info.get("w_2h_for_cell_all")

            cell_2h = info["cell_2h"]
            w_2h = info["w_2h"]
            w_all_for_cell_2h = info.get("w_all_for_cell_2h")
        else:
            # tuple: (out_path, (cell_all,w_all), (cell_2h,w_2h))
            out_path, (cell_all, w_all), (cell_2h, w_2h) = info
            w_2h_for_cell_all = None
            w_all_for_cell_2h = None

        self._after_init_static(
            out_path,
            cell_all,
            w_all,
            w_2h_for_cell_all,
            cell_2h,
            w_2h,
            w_all_for_cell_2h,
        )


    # ---------------- helpers ----------------
    def log_line(self, s: str):
        self.log.insert("end", s + "\n")
        self.log.see("end")

    def _list_result_files(self):
        pattern = os.path.join(self.results_dir, "*.txt")
        files = sorted(glob.glob(pattern))
        return [os.path.basename(p) for p in files]

    def refresh_result_file_list(self):
        names = self._list_result_files()
        self.cmb_files["values"] = names

        current_path = self.last_output_file.get().strip()
        if current_path:
            base = os.path.basename(current_path)
            if base in names:
                self.selected_result_name.set(base)
                return

        if names and not self.selected_result_name.get():
            self.selected_result_name.set(names[-1])

    def _current_result_path(self) -> str:
        # 1) last_output_file
        p = self.last_output_file.get().strip()
        if p and os.path.isfile(p):
            return p

        # 2) combobox selection in Core_FAs
        name = self.selected_result_name.get().strip()
        if name:
            p2 = os.path.join(self.results_dir, name)
            if os.path.isfile(p2):
                self.last_output_file.set(p2)
                return p2

        # 3) latest file
        names = self._list_result_files()
        if names:
            p3 = os.path.join(self.results_dir, names[-1])
            self.selected_result_name.set(names[-1])
            self.last_output_file.set(p3)
            return p3

        return ""

    # ---------------- plotting core ----------------
    def _plot_dose_vs_time_colored(self, times, near_10xT):
        ch = self.chart_time
        ch.del_prev_charts()
        ch.del_log()
        ch.log_line("Dose(t): 10 точек (вплотную)")

        x_min, x_max = min(times), max(times)
        y_max = max(max(s) for s in near_10xT)
        y_min = 0.0

        ch.draw_grid(x_min, x_max, y_min, y_max)

        colors10 = [
            "blue", "red", "green", "orange", "purple",
            "brown", "magenta", "cyan", "gold", "darkgreen"
        ]

        for i in range(10):
            col = colors10[i % len(colors10)]

            def _plot(xs_plot, ys_plot, c=col, chart=ch):
                chart.line_plotter(xs_plot, ys_plot, fill=c, width=2)

            ch.plotValues(times, near_10xT[i], plotter=_plot)

        ch.log_line("Цвета: 1..10 различаются")
        ch.log_line("Файл: " + self._current_result_path())

    def _plot_profile_colored(self, times, near_10xT, far_10xT, t_profile_h: float):
        ch = self.chart_prof
        ch.del_prev_charts()
        ch.del_log()

        idx = closest_index(times, t_profile_h)
        t_used = times[idx]
        ch.log_line(f"Profile(z) при t = {t_used:g} ч (ближайшее к {t_profile_h:g} ч)")

        z = list(range(1, 11))
        near_prof = [near_10xT[i][idx] for i in range(10)]
        far_prof = [far_10xT[i][idx] for i in range(10)]

        x_min, x_max = 1, 10
        y_max = max(max(near_prof), max(far_prof))
        y_min = 0.0

        ch.draw_grid(x_min, x_max, y_min, y_max)

        ch.plotValues(z, near_prof, plotter=lambda xs, ys, chart=ch: chart.line_plotter(xs, ys, fill="blue", width=2))
        ch.plotValues(z, far_prof,  plotter=lambda xs, ys, chart=ch: chart.line_plotter(xs, ys, fill="red", width=2))

        ch.log_line("Синяя: вплотную")
        ch.log_line("Красная: 40 см")
        ch.log_line("Файл: " + self._current_result_path())


    def _after_init_static(
        self,
        out_path: str,
        cell_all: str,
        w_all: float,
        w_2h_for_cell_all: float | None,
        cell_2h: str,
        w_2h: float,
        w_all_for_cell_2h: float | None,
    ):
        self.log_line("InitStaticArray: успешно")
        s1 = f"Макс интеграл за всё время: {cell_all} = {w_all:g} W*hr"
        if w_2h_for_cell_all is not None:
            s1 += f" (а за 2 часа: {w_2h_for_cell_all:g} W*hr)"
        else:
            s1 += " (а за 2 часа: н/д)"

        s2 = f"Макс интеграл за последние 2 ч: {cell_2h} = {w_2h:g} W*hr"
        if w_all_for_cell_2h is not None:
            s2 += f" (а за всё время: {w_all_for_cell_2h:g} W*hr)"
        else:
            s2 += " (а за всё время: н/д)"

        self.log_line("InitStaticArray: успешно")
        self.log_line(s1)
        self.log_line(s2)
        self.log_line(f"Файл сводки: {out_path}")

        self.log_line(f"Сводка по всем ТВС сохранена в файл: {out_path}")

        messagebox.showinfo(
            "Инициализация завершена",
            "Статика успешно инициализирована.\n\n"
            f"Макс интеграл (всё время): {cell_all} = {w_all:g} W*hr\n"
            f"Макс интеграл (последние 2 ч): {cell_2h} = {w_2h:g} W*hr\n\n"
            f"Файл сводки: {out_path}"
        )


    # ---------------- actions ----------------
    def on_init_static(self):
        # If user didn't choose, use default in repo folder (absolute)
        plan_path = self.test_plan_path.get().strip()
        if not plan_path:
            plan_path = os.path.join(self.base_dir, "Configs", "Test_Plan.txt")
            self.test_plan_path.set(plan_path)

        plan_path = os.path.abspath(plan_path)

        def work():
            try:
                # Prefer new signature with plan_file
                try:
                    Test_plan.InitStaticArray(plan_file=plan_path)
                except TypeError:
                    # Backward compatibility (if signature not updated yet)
                    if hasattr(Test_plan, "SetCoreTestPlanFile"):
                        Test_plan.SetCoreTestPlanFile(plan_path)
                    Test_plan.InitStaticArray()

                info = Test_plan.ExportFAEnergyIntegrals()
                self.after(0, lambda d=info: self._show_integrals_after_init(d))

            except Exception as exc:
                # If this is a plan-format error, show dedicated title
                if hasattr(Test_plan, "CoreHistoryInvalid") and isinstance(exc, Test_plan.CoreHistoryInvalid):
                    self.after(0, lambda m=str(exc): messagebox.showerror("Файл не того формата", m))
                else:
                    msg = f"{type(exc).__name__}: {exc}"
                    self.after(0, lambda m=msg: messagebox.showerror("Ошибка инициализации", m))

        threading.Thread(target=work, daemon=True).start()

    def on_calc(self):
        cell = self.last_cell.get().strip()

        try:
            t_h = float(self.last_time.get().replace(",", "."))
        except Exception:
            messagebox.showerror("Ошибка", "Некорректное время (ч).")
            return

        def work():
            try:
                Test_plan.ProcessCell(cell, t_h)

                # ожидаемый файл результата
                out_file = os.path.join(self.results_dir, f"{cell}.txt")

                self.after(0, lambda: self._after_calc(out_file))
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                self.after(0, lambda m=msg: messagebox.showerror("Ошибка расчёта", m))

        self.log_line(f"Расчёт: cell={cell}, time={t_h} ч ...")
        threading.Thread(target=work, daemon=True).start()

    def _after_calc(self, out_file: str):
        self.last_output_file.set(out_file)
        self.profile_t.set(self.last_time.get())

        # синхронизация выбора файла на вкладке графиков
        self.selected_result_name.set(os.path.basename(out_file))
        self.refresh_result_file_list()

        self.log_line(f"Готово. Файл: {out_file}")

        # автообновление графиков
        self.refresh_plots()

        # переключаемся на вкладку графиков
        self.nb.select(self.tab_plot)

    def refresh_plots(self):
        path = self._current_result_path()
        if not path:
            messagebox.showwarning("Нет данных", "Нет файлов результатов. Выполните расчёт или выберите файл.")
            return

        try:
            times, near, far = read_core_fa_file(path)
        except Exception as exc:
            messagebox.showerror("Ошибка чтения файла", f"{type(exc).__name__}: {exc}")
            return

        # Dose(t)
        try:
            self._plot_dose_vs_time_colored(times, near)
        except Exception as exc:
            messagebox.showerror("Ошибка Dose(t)", f"{type(exc).__name__}: {exc}")
            return

        # Profile(z)
        self.refresh_profile_only()

    def refresh_profile_only(self):
        path = self._current_result_path()
        if not path:
            return
        try:
            times, near, far = read_core_fa_file(path)
        except Exception:
            return

        try:
            t_prof = float(self.profile_t.get().replace(",", "."))
        except Exception:
            t_prof = times[-1]

        try:
            self._plot_profile_colored(times, near, far, t_prof)
        except Exception as exc:
            messagebox.showerror("Ошибка профиля", f"{type(exc).__name__}: {exc}")

    def on_combo_file_selected(self, event=None):
        name = self.selected_result_name.get().strip()
        if not name:
            return
        full_path = os.path.join(self.results_dir, name)
        self.last_output_file.set(full_path)

    def on_browse_test_plan(self):
        initial = os.path.join(self.base_dir, "Configs")
        path = filedialog.askopenfilename(
            title="Выберите файл Test_Plan",
            initialdir=initial if os.path.isdir(initial) else self.base_dir,
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if path:
            self.test_plan_path.set(path)


    def on_browse_result_file(self):
        initial = self.results_dir if os.path.isdir(self.results_dir) else self.base_dir
        path = filedialog.askopenfilename(
            title="Выберите файл результата (Core_FAs/*.txt)",
            initialdir=initial,
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not path:
            return

        self.last_output_file.set(path)
        self.selected_result_name.set(os.path.basename(path))
        self.refresh_result_file_list()

        # сразу строим
        self.refresh_plots()

    def on_plot_selected_file(self):
        # строим по выбранному/текущему файлу без расчёта
        self.refresh_plots()
        self.nb_plot.select(self.tab_time)

    def on_plan(self):
        if not _PLANNING_AVAILABLE:
            messagebox.showwarning("Недоступно", "Модули planning.py / tuk_stub.py не найдены.")
            return

        path = self._current_result_path()
        if not path:
            messagebox.showwarning("Нет данных", "Нет файлов результатов. Выполните расчёт или выберите файл.")
            return

        try:
            times, near, far = read_core_fa_file(path)

            limit = float(self.plan_limit.get().replace(",", "."))
            tchk = float(self.plan_tcheck.get().replace(",", "."))
            safety = float(self.plan_safety.get().replace(",", "."))
            crit = self.plan_crit.get().strip()

            tuk_params = TUKStubParams(
                n_fas=int(float(self.tuk_nfas.get().replace(",", "."))),
                k_surface=float(self.tuk_k_surf.get().replace(",", ".")),
                k_1m=float(self.tuk_k_1m.get().replace(",", ".")),
            )

            res = estimate_power_scale(
                times_h=times,
                tvs_near_10xT=near,
                tvs_far_10xT=far,
                limit_value=limit,
                t_check_h=tchk,
                criterion=crit,
                safety_factor=safety,
                tuk_params=tuk_params,
            )

            self.log_line(
                f"Планирование: criterion={res.limited_by}, t={res.t_check_h:g} ч, "
                f"value={res.value_at_check:g}, limit={res.limit:g} => scale={res.scale:g}"
            )

            # Дополнительно посчитаем уставки АЗ по алгоритмам и сохраним в файл
            setp = None
            try:
                plan_path2 = self.test_plan_path.get().strip() or None
                if hasattr(Test_plan, 'ExportAZSetpointsByAlgorithm'):
                    setp = Test_plan.ExportAZSetpointsByAlgorithm(res.scale, plan_file=plan_path2)
                    self.log_line(f"Уставки АЗ сохранены: {setp['out_path']}")
                    for r in setp['rows']:
                        parts = [f"{r['algorithm']} ({r['fas']} FAs):"]
                        for ch, val in sorted(r['currents_nA'].items()):
                            parts.append(f"ch{ch}={val:g} нА")
                        self.log_line("  " + " ".join(parts))
                else:
                    self.log_line("Уставки АЗ не рассчитаны: нет ExportAZSetpointsByAlgorithm() в Test_plan.py")
            except Exception as exc:
                self.log_line(f"Ошибка при расчёте уставок АЗ: {type(exc).__name__}: {exc}")

            # --- Суммарная энерговыработка и экв. расход U-235 по всей АЗ ---
            try:
                plan_path2 = self.test_plan_path.get().strip() or None

                if hasattr(Test_plan, "ComputeCoreEnergyAndU235") and hasattr(Test_plan, "FormatCoreEnergyAndU235Report"):
                    info_plan = Test_plan.ComputeCoreEnergyAndU235(plan_file=plan_path2, scale=1.0, validate_plan=True)
                    info_lim  = Test_plan.ComputeCoreEnergyAndU235(plan_file=plan_path2, scale=res.scale, validate_plan=True)

                    self.log_line("------ Энерговыработка и U-235 ------")
                    for ln in Test_plan.FormatCoreEnergyAndU235Report(info_plan, title="По Test_Plan (без scale)").splitlines():
                        self.log_line(ln)
                    for ln in Test_plan.FormatCoreEnergyAndU235Report(info_lim, title="С учётом scale (по планированию)").splitlines():
                        self.log_line(ln)
                    self.log_line("-------------------------------------")
                else:
                    self.log_line("Энерговыработка/U-235: нет функций ComputeCoreEnergyAndU235/FormatCoreEnergyAndU235Report в Test_plan.py")
            except Exception as exc:
                self.log_line(f"Энерговыработка/U-235 не рассчитаны: {type(exc).__name__}: {exc}")


            # Дополнительно: оценка тока реактиметра (канал 4) по Test_Plan и проверка порога 0.5 нА
            react = None
            try:
                plan_path2 = self.test_plan_path.get().strip() or None
                if hasattr(Test_plan, "ExportReactimeterCurrents"):
                    react = Test_plan.ExportReactimeterCurrents(
                        res.scale,
                        plan_file=plan_path2,
                        Imin_required_nA=0.5,
                        method="geo",
                    )
                    self.log_line(f"Реактиметр: профиль токов сохранён: {react['out_path']}")
                    if react["min_lim_nA"] is not None:
                        status = "OK" if react["ok"] else "НИЖЕ МИНИМУМА"
                        self.log_line(
                            f"Реактиметр: min(I_lim)={react['min_lim_nA']:.6g} нА, "
                            f"порог={react['Imin_required_nA']:.6g} нА => {status}"
                        )
                        if react["min_where"] is not None:
                            t, alg_name, n_fas, N, eff, Ilim = react["min_where"]
                            self.log_line(
                                f"  Минимум при t={t:g} ч, {alg_name}/{n_fas}, N={N:g} W, "
                                f"Eff4={eff:.3e} A/W, I_lim={Ilim:.6g} нА"
                            )
                else:
                    self.log_line("Реактиметр: ExportReactimeterCurrents() не найдена в Test_plan.py")
            except Exception as exc:
                self.log_line(f"Ошибка при оценке реактиметра: {type(exc).__name__}: {exc}")


            msg_lines = [
                f"Допустимое масштабирование мощности: scale = {res.scale:g}",
                f"Ограничение: {res.limited_by}",
                f"t проверки: {res.t_check_h:g} ч",
                f"Значение критерия: {res.value_at_check:g}",
                f"Лимит: {res.limit:g}",
                "",
                "Интерпретация: мощности в Test_Plan можно умножить на scale.",
            ]
            if setp:
                msg_lines += [
                    "",
                    "Уставки АЗ по алгоритмам записаны в файл:",
                    setp['out_path'],
                ]
            if react:
                msg_lines += [
                    "",
                    "Проверка реактиметра (канал 4):",
                    f"min(I_lim) = {react['min_lim_nA']:.6g} нА (порог {react['Imin_required_nA']:.6g} нА) => "
                    + ("OK" if react["ok"] else "НИЖЕ МИНИМУМА"),
                    "Файл токов реактиметра:",
                    react["out_path"],
                ]


            messagebox.showinfo('Результат оценки', "\n".join(msg_lines))
        except Exception as exc:
            messagebox.showerror("Ошибка планирования", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    app = TVSGUI()
    app.mainloop()
