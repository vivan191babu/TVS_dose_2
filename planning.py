# planning.py
# Планирование экспериментов по дозовым ограничениям:
#   "каким коэффициентом можно масштабировать мощность (все режимы Test_Plan),
#    чтобы не превысить заданный контрольный уровень мощности дозы"
#
# Реализовано без повторных запусков ORIGEN:
#   предполагается линейность отклика по мощности для фиксированной истории длительностей
#   (для системы линейных ОДУ накопления/распада это корректная предпосылка).

from dataclasses import dataclass
from typing import List, Tuple, Optional

from tuk_stub import TUKStubParams, tuk_dose_series_from_tvs_near


@dataclass
class PlanningResult:
    scale: float
    limited_by: str
    value_at_check: float
    limit: float
    t_check_h: float


def _closest_index(xs: List[float], x: float) -> int:
    if not xs:
        return 0
    best_i = 0
    best_d = abs(xs[0] - x)
    for i, v in enumerate(xs):
        d = abs(v - x)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _max_at_time(series_list: List[List[float]], t_index: int) -> float:
    # series_list: N series, each length T
    return max(s[t_index] for s in series_list)


def estimate_power_scale(
    times_h: List[float],
    tvs_near_10xT: List[List[float]],
    tvs_far_10xT: List[List[float]],
    limit_value: float,
    t_check_h: float,
    criterion: str = "TVS_NEAR_MAX",
    safety_factor: float = 0.95,
    tuk_params: Optional[TUKStubParams] = None,
) -> PlanningResult:
    """
    Возвращает коэффициент scale, которым можно умножить мощность в Test_Plan,
    чтобы в выбранном критерии не превысить limit_value в момент t_check_h.

    criterion:
      TVS_NEAR_MAX  - максимум по высоте для "вплотную"
      TVS_FAR_MAX   - максимум по высоте для "40 см"
      TUK_SURFACE   - заглушка ТУК на поверхности (по tvs_near)
      TUK_1M        - заглушка ТУК на 1 м (по tvs_near)
      ALL_MAX       - минимум из всех четырёх критериев (консервативно)
    """
    if not times_h:
        raise ValueError("times_h пуст.")
    if len(tvs_near_10xT) != 10 or len(tvs_far_10xT) != 10:
        raise ValueError("Ожидается 10 рядов по высоте для tvs_near_10xT и tvs_far_10xT.")
    T = len(times_h)
    for i in range(10):
        if len(tvs_near_10xT[i]) != T or len(tvs_far_10xT[i]) != T:
            raise ValueError("Длины рядов дозы должны совпадать с times_h.")

    idx = _closest_index(times_h, t_check_h)
    t_used = times_h[idx]

    tuk_params = tuk_params or TUKStubParams()
    tuk_surf, tuk_1m = tuk_dose_series_from_tvs_near(times_h, tvs_near_10xT, tuk_params)

    candidates = {}

    candidates["TVS_NEAR_MAX"] = _max_at_time(tvs_near_10xT, idx)
    candidates["TVS_FAR_MAX"]  = _max_at_time(tvs_far_10xT, idx)
    candidates["TUK_SURFACE"]  = tuk_surf[idx] if tuk_surf else 0.0
    candidates["TUK_1M"]       = tuk_1m[idx] if tuk_1m else 0.0

    if criterion == "ALL_MAX":
        # Берём ограничивающий критерий как тот, кто даёт минимальный scale
        best_scale = float("inf")
        best_key = "TVS_NEAR_MAX"
        best_val = candidates[best_key]
        for k, val in candidates.items():
            if val <= 0:
                continue
            scale_k = limit_value / val
            if scale_k < best_scale:
                best_scale = scale_k
                best_key = k
                best_val = val
        if best_scale == float("inf"):
            best_scale = 0.0
        scale = best_scale * safety_factor
        return PlanningResult(scale=scale, limited_by=best_key, value_at_check=best_val,
                              limit=limit_value, t_check_h=t_used)

    if criterion not in candidates:
        raise ValueError(f"Неизвестный criterion={criterion}")

    value = candidates[criterion]
    if value <= 0:
        scale = 0.0
    else:
        scale = (limit_value / value) * safety_factor

    return PlanningResult(scale=scale, limited_by=criterion, value_at_check=value,
                          limit=limit_value, t_check_h=t_used)
