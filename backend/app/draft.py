"""Бустерный драфт: рассадка по столам, расписание этапов с таймерами, паринги первого тура по рассадке.

Процедура (как ведёт судья, MTR 2019, приложение B «Time Limits»):
  1. Случайная рассадка; больше 8 игроков - несколько столов («подов») по 6-8 человек.
  2. Три бустера: первый передаётся налево, второй направо, третий налево.
  3. Время на пик зависит от числа карт в бустере: 40 с при 15-14 картах … 5 с при 4-2; последнюю карту
     забирают без таймера.
  4. Просмотр взятых карт после бустера: 60 с, каждый следующий на 30 с дольше (60, 90, 120).
  5. Сборка колоды и регистрация деклиста - 25 минут.
  6. Туры по швейцарке; первый - по рассадке: игрок играет с сидящим напротив (место i против i + n/2).

«Берсерк» - Турнирные правила ККИ «Берсерк» (базовая редакция от 26.10.2023), п. 601, 704, 705:
  - столы по 8-16 игроков, число столов - степень двойки (1, 2, 4…), распределение жеребьёвкой (601.3);
  - бустер 12 карт; на пик 60, 55, 50 … 10 секунд (таблица №1), передача налево в нечётных бустерах,
    направо в чётных (601.7); просмотр взятых карт - 1 минута после каждого бустера (601.8);
  - три бустера - колода 30-36 карт, раздача 15 (601.10);
  - тур - 45 минут рекомендованно, организатор может изменить (704.3); первый тур - простая жеребьёвка (705);
  - туров: 3, если за столами меньше 8 игроков, 4 - если 8 и больше (601.3.4).
  Время на сборку колоды правила не задают - по умолчанию 25 минут, как в MTG.

Таймер не тикает на сервере: хранится момент старта, пауза и поправки судьи, а текущий этап вычисляется по
времени. Так экран судьи можно перезагрузить или открыть на другом устройстве - таймер не собьётся.
"""
import random
from datetime import datetime, timezone

# MTR, приложение B: секунды на пик по числу карт в бустере перед пиком
MTG_PICK_SECONDS = {15: 40, 14: 40, 13: 35, 12: 30, 11: 25, 10: 25, 9: 20, 8: 20, 7: 15, 6: 10, 5: 10, 4: 5, 3: 5,
                    2: 5}
DIRECTIONS = ["left", "right", "left", "right", "left"]
POD_MAX = 8


# «Берсерк», таблица №1: 12-карточный бустер, пики 1-11 (в бустере 12…2 карты)
BERSERK_PICK_SECONDS = {12: 60, 11: 55, 10: 50, 9: 45, 8: 40, 7: 35, 6: 30, 5: 25, 4: 20, 3: 15, 2: 10}


def default_config(game: str) -> dict:
    if game == "berserk":
        return {
            "boosters": 3, "cards": 12,
            "pick_seconds": {str(k): v for k, v in BERSERK_PICK_SECONDS.items()},
            "review_first": 60, "review_step": 0,           # 1 минута после каждого бустера (601.8)
            "build_minutes": 25,                            # в Турнирных правилах не задано
            "round_minutes": 50,                            # рекомендовано 45 (704.3), в клубе - 50
            "sets": "", "first_round": "random",            # 705: первый тур - жеребьёвка
            "pod_max": 16, "pods_pow2": True,               # 601.3: столы 8-16, число столов - степень 2
        }
    return {
        "boosters": 3,
        "cards": 14,                                        # MTG Play Booster - 14 карт
        "pick_seconds": {str(k): v for k, v in MTG_PICK_SECONDS.items()},
        "review_first": 60, "review_step": 30,             # 60, 90, 120 с
        "build_minutes": 25,
        "round_minutes": 50,
        "sets": "",                                         # «7-8-8» - выпуски бустеров, для подписи
        "first_round": "seats",                             # seats - по рассадке | random
        "pod_max": 8, "pods_pow2": False,
    }


def clean_config(cfg: dict, game: str) -> dict:
    """Проверка настроек судьи: разумные пределы, недостающее - по умолчанию."""
    base = default_config(game)
    out = {**base, **{k: v for k, v in (cfg or {}).items() if k in base}}
    out["boosters"] = max(1, min(int(out["boosters"]), 6))
    out["cards"] = max(2, min(int(out["cards"]), 30))
    secs = {}
    for n in range(2, out["cards"] + 1):
        fallback = BERSERK_PICK_SECONDS if game == "berserk" else MTG_PICK_SECONDS
        v = (out.get("pick_seconds") or {}).get(str(n), fallback.get(n, max(fallback.values())))
        secs[str(n)] = max(1, min(int(v), 600))
    out["pick_seconds"] = secs
    out["review_first"] = max(0, min(int(out["review_first"]), 900))
    out["review_step"] = max(0, min(int(out["review_step"]), 900))
    out["build_minutes"] = max(1, min(int(out["build_minutes"]), 180))
    out["round_minutes"] = max(10, min(int(out["round_minutes"]), 180))
    out["sets"] = str(out.get("sets") or "")[:40]
    out["first_round"] = "random" if out.get("first_round") == "random" else "seats"
    out["pod_max"] = max(2, min(int(out["pod_max"]), 32))
    out["pods_pow2"] = bool(out["pods_pow2"])
    return out


def timeline(cfg: dict) -> list[dict]:
    """Этапы драфта по порядку: пики каждого бустера, просмотр после него, сборка колоды."""
    steps: list[dict] = []
    for pack in range(1, cfg["boosters"] + 1):
        direction = DIRECTIONS[pack - 1]
        for pick, left in enumerate(range(cfg["cards"], 1, -1), 1):
            steps.append({"kind": "pick", "pack": pack, "pick": pick, "cards_left": left, "direction": direction,
                          "seconds": int(cfg["pick_seconds"][str(left)])})
        review = cfg["review_first"] + cfg["review_step"] * (pack - 1)
        if review:
            steps.append({"kind": "review", "pack": pack, "seconds": review})
    steps.append({"kind": "build", "seconds": cfg["build_minutes"] * 60})
    return steps


def _ts(v) -> datetime | None:
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def elapsed(state: dict, now: datetime) -> float:
    """Сколько секунд расписания прошло: от старта, минус паузы, плюс поправки судьи («пропустить», «+время»)."""
    started = _ts(state.get("started_at"))
    if not started:
        return 0.0
    paused = _ts(state.get("paused_at"))
    return ((paused or now) - started).total_seconds() + float(state.get("offset", 0))


def current(cfg: dict, state: dict, now: datetime | None = None) -> dict:
    """Текущий этап и остаток времени. stage: seating (ещё не начали) | pick | review | build | done."""
    now = now or datetime.now(timezone.utc)
    steps = steps_with_extra(cfg, state)
    total = sum(s["seconds"] for s in steps)
    if not state.get("started_at"):
        return {"stage": "seating", "index": -1, "steps": len(steps), "total": total}
    t = elapsed(state, now)
    acc = 0.0
    for i, s in enumerate(steps):
        if t < acc + s["seconds"]:
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            return {"stage": s["kind"], "index": i, "steps": len(steps), "total": total, "step": s,
                    "left": round(acc + s["seconds"] - t, 2), "step_started": acc, "elapsed": round(t, 2),
                    "next": nxt, "paused": bool(state.get("paused_at"))}
        acc += s["seconds"]
    return {"stage": "done", "index": len(steps), "steps": len(steps), "total": total, "paused": False}


def skip(cfg: dict, state: dict, now: datetime) -> dict:
    """Сразу к следующему этапу: поправка = остаток текущего."""
    cur = current(cfg, state, now)
    if cur["stage"] in ("seating", "done"):
        return state
    end = cur["step_started"] + cur["step"]["seconds"]          # точный конец этапа (left округлён)
    return {**state, "offset": float(state.get("offset", 0)) + (end - elapsed(state, now)) + 0.001}


def steps_with_extra(cfg: dict, state: dict) -> list[dict]:
    """Расписание с добавленным судьёй временем по этапам (state.extra: {номер этапа: секунды})."""
    extra = state.get("extra") or {}
    return [{**s, "seconds": s["seconds"] + float(extra.get(str(i), 0))} for i, s in enumerate(timeline(cfg))]


def add_time(cfg: dict, state: dict, now: datetime, seconds: float) -> dict:
    """«+N секунд» к текущему этапу: продлевается именно он, следующие сдвигаются."""
    cur = current(cfg, state, now)
    if cur["stage"] in ("seating", "done"):
        return state
    extra = dict(state.get("extra") or {})
    extra[str(cur["index"])] = float(extra.get(str(cur["index"]), 0)) + seconds
    return {**state, "extra": extra}


def pods(n: int, pod_max: int = POD_MAX, pow2: bool = False) -> list[int]:
    """Размеры столов: не больше pod_max, как можно ровнее (MTG: 10 -> 5+5, 17 -> 6+6+5).
    pow2 («Берсерк»): число столов - степень двойки (40 при 16 на стол -> 4 стола по 10)."""
    if n <= 0:
        return []
    k = -(-n // pod_max)
    if pow2:
        k = 1 << (k - 1).bit_length()
    base, extra = divmod(n, k)
    return [base + 1] * extra + [base] * (k - extra)


def seat(user_ids: list[int], rng: random.Random | None = None, pod_max: int = POD_MAX,
         pow2: bool = False) -> list[tuple[int, int, int]]:
    """Случайная рассадка: [(user_id, стол, место)], места с 1 по часовой стрелке."""
    ids = list(user_ids)
    (rng or random).shuffle(ids)
    out, i = [], 0
    for pod_no, size in enumerate(pods(len(ids), pod_max, pow2), 1):
        for s in range(1, size + 1):
            out.append((ids[i], pod_no, s))
            i += 1
    return out


def first_round_pairs(seating: list[tuple[int, int, int]]) -> list[tuple[int, int | None]]:
    """Первый тур по рассадке: за каждым столом место i играет с местом i + n/2 (сидящим напротив, не соседом
    по передаче). Нечётный стол: последнее место без пары; такие игроки разных столов играют между собой,
    последний оставшийся получает bye."""
    by_pod: dict[int, list[tuple[int, int]]] = {}
    for uid, pod, s in seating:
        by_pod.setdefault(pod, []).append((s, uid))
    pairs, spare = [], []
    for pod in sorted(by_pod):
        order = [uid for _, uid in sorted(by_pod[pod])]
        half = len(order) // 2
        pairs += [(order[i], order[i + half]) for i in range(half)]
        if len(order) % 2:
            spare.append(order[-1])
    while len(spare) >= 2:
        pairs.append((spare.pop(0), spare.pop(0)))
    if spare:
        pairs.append((spare[0], None))
    return pairs
