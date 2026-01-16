# plot_from_file.py
# Чтение файлов Core_FAs/<cell>.txt и построение:
#   (1) Dose(t) для 10 точек "вплотную"
#   (2) Профиль dose(z) для выбранного времени (две кривые: "вплотную" и "40 см")

from __future__ import annotations
from typing import List, Tuple, Optional
import os
import tkinter as tk
from tkinter import ttk, messagebox

import Chart


def read_core_fa_file(path: str) -> Tuple[List[float], List[List[float]], List[List[float]]]:
    """
    Формат файла:
      col1: time[h]
      col2-11:  near (10 точек)
      col12-21: far  (10 точек)

    Возврат:
      times_h: [T]
      near_10xT: 10 списков по T
      far_10xT : 10 списков по T
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    times: List[float] = []
    near: List[List[float]] = [[] for _ in range(10)]
    far:  List[List[float]] = [[] for _ in range(10)]

    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                continue
            parts = s.replace(",", ".").split()
            if len(parts) < 21:
                # иногда могут быть заголовки — просто пропускаем
                continue
            row = [float(x) for x in parts[:21]]
            t = row[0]
            times.append(t)
            for i in range(10):
                near[i].append(row[1 + i])
                far[i].append(row[11 + i])

    if not times:
        raise ValueError(f"Файл не содержит данных: {path}")

    return times, near, far


def _closest_index(xs: List[float], x: float) -> int:
    best_i = 0
    best_d = abs(xs[0] - x)
    for i, v in enumerate(xs):
        d = abs(v - x)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def plot_dose_vs_time(
    chart: Chart.ChartMainWindow,
    times_h: List[float],
    near_10xT: List[List[float]],
    title: str = "Мощность дозы от времени (вплотную)",
) -> None:
    chart.del_prev_charts()
    chart.del_log()
    chart.log_line(title)

    y_max = max(max(s) for s in near_10xT)
    y_min = 0.0
    x_min = min(times_h)
    x_max = max(times_h)

    chart.draw_grid(x_min, x_max, y_min, y_max)

    # 10 кривых
    for i in range(10):
        chart.plotValues(
            times_h, near_10xT[i],
            plotter=lambda xs, ys, i=i: chart.line_plotter(xs, ys)
        )

    chart.log_line("Построено кривых: 10")


def plot_profile_at_time(
    chart: Chart.ChartMainWindow,
    times_h: List[float],
    near_10xT: List[List[float]],
    far_10xT: List[List[float]],
    t_profile_h: float,
    title: str = "Профиль мощности дозы по высоте",
) -> None:
    chart.del_prev_charts()
    chart.del_log()

    idx = _closest_index(times_h, t_profile_h)
    t_used = times_h[idx]
    chart.log_line(f"{title}. t = {t_used:g} ч (ближайшее к {t_profile_h:g} ч)")

    # высота — условно 1..10 (как индекс точки контроля)
    z = list(range(1, 11))
    near_prof = [near_10xT[i][idx] for i in range(10)]
    far_prof  = [far_10xT[i][idx] for i in range(10)]

    y_max = max(max(near_prof), max(far_prof))
    y_min = 0.0
    x_min = 1
    x_max = 10

    chart.draw_grid(x_min, x_max, y_min, y_max)

    chart.plotValues(z, near_prof, plotter=lambda xs, ys: chart.line_plotter(xs, ys))
    chart.plotValues(z, far_prof,  plotter=lambda xs, ys: chart.line_plotter(xs, ys))

    chart.log_line("Кривые: 2 (вплотную / 40 см)")


# --- Опционально: автономный запуск ---
def _run_standalone(path: str) -> None:
    times, near, far = read_core_fa_file(path)

    root = tk.Tk()
    root.title("Просмотр результатов расчёта дозы")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)

    tab1 = ttk.Frame(nb)
    tab2 = ttk.Frame(nb)
    nb.add(tab1, text="Dose(t)")
    nb.add(tab2, text="Profile(z)")

    ch1 = Chart.ChartMainWindow(tab1)
    ch2 = Chart.ChartMainWindow(tab2)

    # controls for profile
    ctrl = ttk.Frame(tab2)
    ctrl.grid(row=0, column=0, sticky="ew")
    ttk.Label(ctrl, text="t, ч:").pack(side="left")
    t_var = tk.StringVar(value=str(times[-1]))
    t_ent = ttk.Entry(ctrl, width=10, textvariable=t_var)
    t_ent.pack(side="left", padx=5)

    def refresh():
        plot_dose_vs_time(ch1, times, near)
        try:
            t_val = float(t_var.get().replace(",", "."))
        except Exception:
            messagebox.showerror("Ошибка", "Некорректное t")
            return
        plot_profile_at_time(ch2, times, near, far, t_val)

    ttk.Button(ctrl, text="Обновить", command=refresh).pack(side="left", padx=8)

    refresh()
    root.mainloop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python plot_from_file.py Core_FAs/1-1.txt")
        raise SystemExit(2)
    _run_standalone(sys.argv[1])
