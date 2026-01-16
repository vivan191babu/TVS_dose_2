# tvs_gui.py
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import Test_plan
import Chart
import plot_from_file
from planning import estimate_power_scale
from tuk_stub import TUKStubParams


class TVSGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TVS_dose_2 — расчёт и визуализация")
        self.geometry("1200x700")

        self.last_cell = tk.StringVar(value="1-1")
        self.last_time = tk.StringVar(value="10")
        self.last_output_file = tk.StringVar(value="")

        # planning controls
        self.plan_limit = tk.StringVar(value="1000")   # мкЗв/ч (пример)
        self.plan_tcheck = tk.StringVar(value="0")
        self.plan_safety = tk.StringVar(value="0.95")
        self.plan_crit = tk.StringVar(value="ALL_MAX")

        self.tuk_nfas = tk.StringVar(value="7")
        self.tuk_k_surf = tk.StringVar(value="0.08")
        self.tuk_k_1m = tk.StringVar(value="0.015")

        # profile time
        self.profile_t = tk.StringVar(value="10")

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.tab_calc = ttk.Frame(self.nb)
        self.tab_plot = ttk.Frame(self.nb)

        self.nb.add(self.tab_calc, text="Расчёт")
        self.nb.add(self.tab_plot, text="Графики")

        self._build_calc_tab()
        self._build_plot_tab()

    # ---------------- UI ----------------
    def _build_calc_tab(self):
        top = ttk.Frame(self.tab_calc, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="1) Инициализировать статику", command=self.on_init_static).pack(side="left")
        ttk.Label(top, text="   Ячейка:").pack(side="left", padx=(15, 3))
        ttk.Entry(top, width=10, textvariable=self.last_cell).pack(side="left")

        ttk.Label(top, text="Время, ч:").pack(side="left", padx=(10, 3))
        ttk.Entry(top, width=10, textvariable=self.last_time).pack(side="left")

        ttk.Button(top, text="2) Рассчитать", command=self.on_calc).pack(side="left", padx=(15, 0))

        mid = ttk.Frame(self.tab_calc, padding=10)
        mid.pack(fill="x")

        ttk.Label(mid, text="Выходной файл:").pack(side="left")
        ttk.Entry(mid, width=80, textvariable=self.last_output_file).pack(side="left", padx=8)

        ttk.Button(mid, text="Построить графики", command=self.refresh_plots).pack(side="left", padx=8)

        # Planning block
        grp = ttk.LabelFrame(self.tab_calc, text="Планирование по дозовым ограничениям (оценка масштаба мощности)", padding=10)
        grp.pack(fill="x", padx=10, pady=10)

        row1 = ttk.Frame(grp)
        row1.pack(fill="x")
        ttk.Label(row1, text="Ограничение, (ед. как в файле):").pack(side="left")
        ttk.Entry(row1, width=12, textvariable=self.plan_limit).pack(side="left", padx=6)
        ttk.Label(row1, text="t контроля, ч:").pack(side="left", padx=(10, 3))
        ttk.Entry(row1, width=8, textvariable=self.plan_tcheck).pack(side="left")
        ttk.Label(row1, text="коэф. запаса:").pack(side="left", padx=(10, 3))
        ttk.Entry(row1, width=8, textvariable=self.plan_safety).pack(side="left")

        row2 = ttk.Frame(grp)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Критерий:").pack(side="left")
        crit = ttk.Combobox(
            row2, width=18, textvariable=self.plan_crit, state="readonly",
            values=["TVS_NEAR_MAX", "TVS_FAR_MAX", "TUK_SURFACE", "TUK_1M", "ALL_MAX"]
        )
        crit.pack(side="left", padx=6)

        ttk.Label(row2, text="ТУК: N ТВС=").pack(side="left", padx=(10, 3))
        ttk.Entry(row2, width=6, textvariable=self.tuk_nfas).pack(side="left")
        ttk.Label(row2, text="k_пов=").pack(side="left", padx=(10, 3))
        ttk.Entry(row2, width=6, textvariable=self.tuk_k_surf).pack(side="left")
        ttk.Label(row2, text="k_1м=").pack(side="left", padx=(10, 3))
        ttk.Entry(row2, width=6, textvariable=self.tuk_k_1m).pack(side="left")

        ttk.Button(row2, text="Оценить коэффициент масштаба мощности", command=self.on_plan).pack(side="left", padx=12)

        # Log
        self.log = tk.Text(self.tab_calc, height=18)
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_plot_tab(self):
        # Внутри вкладки "Графики" делаем ещё один Notebook, чтобы показывать два графика
        top = ttk.Frame(self.tab_plot, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="t для профиля (ч):").pack(side="left")
        ttk.Entry(top, width=10, textvariable=self.profile_t).pack(side="left", padx=6)
        ttk.Button(top, text="Обновить профиль", command=self.refresh_profile_only).pack(side="left", padx=6)

        ttk.Label(top, text="Файл:").pack(side="left", padx=(20, 3))
        ttk.Label(top, textvariable=self.last_output_file).pack(side="left")

        self.nb_plot = ttk.Notebook(self.tab_plot)
        self.nb_plot.pack(fill="both", expand=True)

        self.tab_time = ttk.Frame(self.nb_plot)
        self.tab_prof = ttk.Frame(self.nb_plot)
        self.nb_plot.add(self.tab_time, text="Dose(t) — вплотную")
        self.nb_plot.add(self.tab_prof, text="Profile(z) — вплотную/40см")

        self.chart_time = Chart.ChartMainWindow(self.tab_time)
        self.chart_prof = Chart.ChartMainWindow(self.tab_prof)

    # ---------------- actions ----------------
    def log_line(self, s: str):
        self.log.insert("end", s + "\n")
        self.log.see("end")

    def on_init_static(self):
        def work():
            try:
                Test_plan.InitStaticArray()
                self.after(0, lambda: self.log_line("InitStaticArray: успешно"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Ошибка инициализации", str(e)))

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
                out_file = Test_plan.ProcessCell_AndReturnFile(cell, t_h)
                self.after(0, lambda: self._after_calc(out_file))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Ошибка расчёта", str(e)))

        self.log_line(f"Расчёт: cell={cell}, time={t_h} ч ...")
        threading.Thread(target=work, daemon=True).start()

    def _after_calc(self, out_file: str):
        self.last_output_file.set(out_file)
        self.profile_t.set(self.last_time.get())
        self.log_line(f"Готово. Файл: {out_file}")
        # Автообновление графиков
        self.refresh_plots()
        # Переключаемся на вкладку графиков
        self.nb.select(self.tab_plot)

    def refresh_plots(self):
        path = self.last_output_file.get().strip()
        if not path:
            messagebox.showwarning("Нет данных", "Сначала выполните расчёт.")
            return
        try:
            times, near, far = plot_from_file.read_core_fa_file(path)
        except Exception as e:
            messagebox.showerror("Ошибка чтения файла", str(e))
            return

        try:
            plot_from_file.plot_dose_vs_time(self.chart_time, times, near)
        except Exception as e:
            messagebox.showerror("Ошибка построения Dose(t)", str(e))
            return

        self.refresh_profile_only()

    def refresh_profile_only(self):
        path = self.last_output_file.get().strip()
        if not path:
            return
        try:
            times, near, far = plot_from_file.read_core_fa_file(path)
            t_prof = float(self.profile_t.get().replace(",", "."))
            plot_from_file.plot_profile_at_time(self.chart_prof, times, near, far, t_prof)
        except Exception as e:
            messagebox.showerror("Ошибка построения профиля", str(e))

    def on_plan(self):
        path = self.last_output_file.get().strip()
        if not path:
            messagebox.showwarning("Нет данных", "Сначала выполните расчёт и получите файл результата.")
            return
        try:
            times, near, far = plot_from_file.read_core_fa_file(path)

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
            messagebox.showinfo(
                "Результат планирования",
                f"Оценка коэффициента масштаба мощности: scale = {res.scale:g}\n"
                f"Ограничивает: {res.limited_by}\n"
                f"t контроля: {res.t_check_h:g} ч\n"
                f"значение в точке: {res.value_at_check:g}\n"
                f"лимит: {res.limit:g}\n\n"
                f"Интерпретация: мощности в Test_Plan можно умножить на scale."
            )
        except Exception as e:
            messagebox.showerror("Ошибка планирования", str(e))


if __name__ == "__main__":
    app = TVSGUI()
    app.mainloop()
