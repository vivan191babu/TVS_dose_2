import os
import tkinter as tk
from tkinter import ttk, messagebox

import Test_plan as tp  # модуль из твоего проекта

# Базовый каталог – там, где лежит этот скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "Core_FAs")  # папка с результатами расчёта от ячеек


class TVSDoseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TVS_dose – расчёт дозы по ячейке")
        self.geometry("520x260")
        self.resizable(False, False)

        self.static_initialized = False
        self.algorithms = None
        self.greens = None

        self._build_ui()

    def _build_ui(self):
        # --- Блок 1. Инициализация статики ---
        frame_static = ttk.LabelFrame(self, text="Шаг 1. Инициализация статики")
        frame_static.pack(fill="x", padx=10, pady=10)

        self.static_status = ttk.Label(
            frame_static, text="Статус: статика не инициализирована"
        )
        self.static_status.pack(side="left", padx=5, pady=5)

        self.btn_init = ttk.Button(
            frame_static, text="Инициализировать", command=self.on_init_static
        )
        self.btn_init.pack(side="right", padx=5, pady=5)

        # --- Блок 2. Ввод ячейки и времени ---
        frame_calc = ttk.LabelFrame(self, text="Шаг 2. Расчёт дозы для ячейки")
        frame_calc.pack(fill="x", padx=10, pady=10)

        row1 = ttk.Frame(frame_calc)
        row1.pack(fill="x", padx=5, pady=5)
        ttk.Label(row1, text="Ячейка ТВС (cell):").pack(side="left")
        self.entry_cell = ttk.Entry(row1, width=15)
        self.entry_cell.pack(side="left", padx=5)

        row2 = ttk.Frame(frame_calc)
        row2.pack(fill="x", padx=5, pady=5)
        ttk.Label(row2, text="Время расчёта, ч:").pack(side="left")
        self.entry_hours = ttk.Entry(row2, width=10)
        self.entry_hours.pack(side="left", padx=5)

        self.btn_calc = ttk.Button(
            frame_calc, text="Рассчитать", command=self.on_calc
        )
        self.btn_calc.pack(side="right", padx=5, pady=5)

        # --- Блок 3. Результат ---
        self.result_label = ttk.Label(self, text="Выходной файл: —")
        self.result_label.pack(fill="x", padx=10, pady=10)

    # ----------------- Колбэки -----------------

    def on_init_static(self):
        """Инициализация статики через InitStaticArray()."""
        try:
            self.static_status.config(text="Статус: идёт инициализация...")
            self.update_idletasks()

            # вызываем инициализацию статики
            res = tp.InitStaticArray() 

            # Пытаемся взять результат либо из возврата функции,
            # либо из глобальных переменных модуля Test_plan
            if isinstance(res, tuple) and len(res) == 2:
                algorithms, greens = res
            else:
            # в твоём текущем коде InitStaticArray() просто
            # заполняет глобальные переменные tp.Algorithms и tp.Greens
                algorithms = getattr(tp, "Algorithms", None)
                greens = getattr(tp, "Greens", None)

            if algorithms is None or greens is None:
                raise RuntimeError("InitStaticArray не вернула данные и не заполнила Algorithms/Greens")
    
            tp.Algorithms = algorithms
            tp.Greens = greens
            self.algorithms = algorithms
            self.greens = greens  
            self.static_initialized = True
            self.static_status.config(
                text=f"Статус: статика инициализирована (алгоритмов: {len(algorithms)})"
                )
        except Exception as e:
            self.static_initialized = False
            self.static_status.config(text="Статус: ошибка инициализации")
            messagebox.showerror(
                "Ошибка",
                f"Не удалось инициализировать статику:\n{e}",
            )

    def on_calc(self):
        """Запуск ProcessCell с выбранной ячейкой и временем."""
        if not self.static_initialized:
            messagebox.showwarning(
                "Нет статики",
                "Сначала инициализируйте статику (Шаг 1).",
            )
            return

        cell = self.entry_cell.get().strip()
        if not cell:
            messagebox.showwarning(
                "Нет ячейки",
                "Укажите идентификатор ячейки (например, 1-1).",
            )
            return

        hours_str = self.entry_hours.get().strip()
        try:
            hours = float(hours_str)
            if hours <= 0:
                raise ValueError
        except Exception:
            messagebox.showwarning(
                "Некорректное время",
                "Введите положительное число часов (например, 320).",
            )
            return

        # Снимем список файлов в каталоге результатов ДО расчёта
        try:
            before_files = (
                set(os.listdir(RESULTS_DIR)) if os.path.isdir(RESULTS_DIR) else set()
            )
        except Exception:
            before_files = set()

        try:
            self.result_label.config(text="Выполняется расчёт...")
            self.update_idletasks()

            # Запуск основного расчёта
            tp.ProcessCell(cell, hours)

            # Список файлов ПОСЛЕ расчёта
            try:
                after_files = (
                    set(os.listdir(RESULTS_DIR))
                    if os.path.isdir(RESULTS_DIR)
                    else set()
                )
            except Exception:
                after_files = set()

            new_files = sorted(after_files - before_files)

            if new_files:
                # Обычно будет один файл, но покажем все новые
                files_str = ", ".join(new_files)
                self.result_label.config(
                    text=f"Выходной файл(ы): {files_str}"
                )
                messagebox.showinfo(
                    "Расчёт завершён",
                    "Расчёт успешно выполнен.\n"
                    "Новые файлы в каталоге Core_FAs:\n" + "\n".join(new_files),
                )
            else:
                self.result_label.config(
                    text="Выходной файл: не обнаружен (проверьте папку Core_FAs)"
                )
                messagebox.showinfo(
                    "Расчёт завершён",
                    "Расчёт выполнен, но новые файлы в Core_FAs не обнаружены.\n"
                    "Проверьте логи и настройки.",
                )

        except Exception as e:
            self.result_label.config(text="Ошибка при расчёте")
            messagebox.showerror(
                "Ошибка",
                f"Ошибка при выполнении ProcessCell:\n{e}",
            )


if __name__ == "__main__":
    app = TVSDoseApp()
    app.mainloop()
