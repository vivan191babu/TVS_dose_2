#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
plot_from_file.py

Визуализация результатов расчёта мощности дозы от одной ТВС
по файлу вида Core_FAs/<cell>.txt (формат как в 1-1.txt).

Строятся ДВА графика:
  1) Мощность дозы во времени (10 точек "вплотную").
  2) Профиль мощности дозы по высоте в момент времени t*,
     задаваемый пользователем (две кривые: вплотную и на 40 см).

Запуск:
    python plot_from_file.py                 # диалог выбора файла
    python plot_from_file.py Core_FAs/1-1.txt
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import Chart  # модуль с ChartMainWindow


# ----------------------- ЧТЕНИЕ ДАННЫХ ----------------------- #

def parse_result_file(path):
    """
    Читает файл результата вида Core_FAs/1-1.txt.

    Формат:
        - первая колонка  : время, ч (float)
        - колонки 2–11    : мощность дозы "вплотную" в 10 точках по высоте
        - колонки 12–21   : мощность дозы на расстоянии 40 см в 10 точках

    Возвращает:
        times : list[float]
        near  : list[list[float]] длиной 10
        far   : list[list[float]] длиной 10
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Файл не найден: {path}")

    times = []
    near = [[] for _ in range(10)]
    far = [[] for _ in range(10)]

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 21:
                # строка слишком короткая — пропускаем
                continue

            try:
                vals = [float(x.replace(",", ".")) for x in parts]
            except ValueError:
                # нечисловая строка — пропускаем
                continue

            t = vals[0]
            times.append(t)

            # 2–11: вплотную
            for i in range(10):
                near[i].append(vals[1 + i])

            # 12–21: на 40 см
            for i in range(10):
                far[i].append(vals[11 + i])

    if not times:
        raise ValueError(f"Не удалось прочитать данные из файла {path}")

    return times, near, far


# ----------------------- ПОСТРОЕНИЕ ГРАФИКОВ ----------------------- #

def show_chart_for_file(path):
    """
    Строит два графика по файлу результата:
      1) доза(t) для 10 точек "вплотную";
      2) доза(h) (профиль по высоте) в момент времени t*.
    """
    times, near, far = parse_result_file(path)

    # --- спрашиваем время t* для профиля по высоте ---
    # используем невидимый root только для диалога
    root = tk.Tk()
    root.withdraw()

    t_min, t_max = min(times), max(times)
    prompt = (
        f"Введите время в часах для профиля по высоте.\n"
        f"Допустимый диапазон: от {t_min:.3g} до {t_max:.3g}.\n"
        f"Если оставить по умолчанию, будет использовано {t_max:.3g} ч."
    )
    t_profile = simpledialog.askfloat(
        "Время для профиля по высоте",
        prompt,
        initialvalue=t_max,
        parent=root,
    )
    if t_profile is None:
        # Пользователь нажал Cancel — используем последний момент
        t_profile = t_max

    # Находим индекс ближайшего времени
    idx_profile = min(range(len(times)), key=lambda i: abs(times[i] - t_profile))
    t_used = times[idx_profile]

    # Теперь создаём два окна с графиками
    root.deiconify()
    root.title(f"Графики дозы: {os.path.basename(path)}")

    # --- Окно 1: доза(t) для 10 точек "вплотную" ---
    top_time = tk.Toplevel(root)
    top_time.title("Доза во времени (вплотную)")

    chart_time = Chart.ChartMainWindow(top_time)

    # Диапазоны по осям
    x_min = t_min
    x_max = t_max

    all_near_vals = [v for series in near for v in series]
    y_min = min(all_near_vals)
    y_max = max(all_near_vals)

    if y_max == y_min:
        y_min *= 0.9
        y_max *= 1.1
    else:
        dy = y_max - y_min
        y_min -= 0.05 * dy
        y_max += 0.05 * dy

    chart_time.draw_grid(x_min, x_max, y_min, y_max)

    colors = [
        "blue", "red", "green", "orange", "purple",
        "brown", "magenta", "cyan", "black", "gray"
    ]

    for i in range(10):
        color = colors[i % len(colors)]

        def _plot(xs_plot, ys_plot, col=color, ch=chart_time):
            ch.line_plotter(xs_plot, ys_plot, fill=col)

        chart_time.plotValues(times, near[i], _plot)

        try:
            vmin = min(near[i])
            vmax = max(near[i])
            chart_time.log_line(
                f"Кривая {i+1} (вплотную): min={vmin:.3g}, max={vmax:.3g}"
            )
        except Exception:
            pass

    chart_time.log_line(f"Для профиля по высоте использовано время t* = {t_used:.3g} ч")

    # --- Окно 2: профиль по высоте в момент t* ---
    top_prof = tk.Toplevel(root)
    top_prof.title(f"Профиль по высоте при t = {t_used:.3g} ч")

    chart_prof = Chart.ChartMainWindow(top_prof)

    heights = list(range(1, 11))  # номера точек снизу вверх 1..10

    near_profile = [near[i][idx_profile] for i in range(10)]
    far_profile = [far[i][idx_profile] for i in range(10)]

    all_prof_vals = near_profile + far_profile
    y2_min = min(all_prof_vals)
    y2_max = max(all_prof_vals)
    x2_min, x2_max = 1.0, 10.0

    if y2_max == y2_min:
        y2_min *= 0.9
        y2_max *= 1.1
    else:
        dy2 = y2_max - y2_min
        y2_min -= 0.05 * dy2
        y2_max += 0.05 * dy2

    chart_prof.draw_grid(x2_min, x2_max, y2_min, y2_max)

    # Кривая "вплотную" (синим)
    def _plot_near(xs_plot, ys_plot, ch=chart_prof):
        ch.line_plotter(xs_plot, ys_plot, fill="blue")

    chart_prof.plotValues(heights, near_profile, _plot_near)
    chart_prof.log_line("Синяя линия: доза вплотную")

    # Кривая "на 40 см" (красным)
    def _plot_far(xs_plot, ys_plot, ch=chart_prof):
        ch.line_plotter(xs_plot, ys_plot, fill="red")

    chart_prof.plotValues(heights, far_profile, _plot_far)
    chart_prof.log_line("Красная линия: доза на расстоянии 40 см")

    chart_prof.log_line(f"Профиль по высоте при t = {t_used:.3g} ч")

    # главный цикл
    root.mainloop()


# ----------------------- ЗАПУСК ----------------------- #

def ask_file_and_show_chart():
    """Диалог выбора файла и построение двух графиков."""
    root = tk.Tk()
    root.withdraw()

    initial_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "Core_FAs",
    )
    if not os.path.isdir(initial_dir):
        initial_dir = os.path.dirname(os.path.abspath(__file__))

    path = filedialog.askopenfilename(
        title="Выберите файл результата (Core_FAs/*.txt)",
        initialdir=initial_dir,
        filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
    )

    if not path:
        messagebox.showinfo("Отмена", "Файл не выбран.")
        root.destroy()
        return

    root.destroy()

    try:
        show_chart_for_file(path)
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось построить графики:\n{e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        try:
            show_chart_for_file(file_path)
        except Exception as exc:
            print(f"Ошибка при построении графиков для файла {file_path}:\n{exc}")
            sys.exit(1)
    else:
        ask_file_and_show_chart()
