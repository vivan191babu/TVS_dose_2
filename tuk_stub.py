# tuk_stub.py
# Заглушечная модель дозы от ТУК.
# ВНИМАНИЕ: это не физическая модель. Она нужна, чтобы:
#   1) встроить расчёт ТУК в общий контур интерфейсов,
#   2) иметь возможность планирования по ограничениям ТУК,
#   3) позже заменить на Green-функции ТУК без изменения GUI/логики.

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class TUKStubParams:
    # Число ТВС в ТУК (пример: 6/7/8 — зависит от конкретного ТУК)
    n_fas: int = 7

    # Коэффициенты пересчёта от "реперной" дозы ТВС -> дозе от ТУК.
    # Их смысл: условное экранирование + геометрия.
    # Подбираются позже по расчетам/эксперименту.
    k_surface: float = 0.08
    k_1m: float = 0.015


def tuk_dose_series_from_tvs_near(
    times_h: List[float],
    tvs_near_10xT: List[List[float]],
    params: TUKStubParams = TUKStubParams(),
) -> Tuple[List[float], List[float]]:
    """
    Строит временные ряды дозы от ТУК (поверхность и 1 м) по заглушечной модели.

    Вход:
      times_h         : список времен (часы)
      tvs_near_10xT   : 10 рядов "вплотную", каждый длины T (мкЗв/ч или Зв/ч — как в файле)

    Выход:
      tuk_surface[t], tuk_1m[t] : ряды по времени
    """
    if not times_h:
        return [], []
    if not tvs_near_10xT or len(tvs_near_10xT) != 10:
        raise ValueError("tvs_near_10xT должен быть списком из 10 рядов (по высоте).")

    T = len(times_h)
    for i in range(10):
        if len(tvs_near_10xT[i]) != T:
            raise ValueError("Длины рядов tvs_near_10xT должны совпадать с times_h.")

    # Берём реперную величину как максимум по высоте в каждый момент времени (консервативно)
    base_max = [max(tvs_near_10xT[z][t] for z in range(10)) for t in range(T)]

    tuk_surface = [params.n_fas * params.k_surface * v for v in base_max]
    tuk_1m      = [params.n_fas * params.k_1m      * v for v in base_max]
    return tuk_surface, tuk_1m
