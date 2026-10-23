/** Рейтинг силы: дисциплины и уровни турниров (как в backend/app/rating.py). */
export const DISCIPLINES: [string, string, "mtg" | "berserk"][] = [
  ["mtg_constructed", "Констракт", "mtg"],
  ["mtg_draft", "Драфт", "mtg"],
  ["mtg_edh", "EDH", "mtg"],
  ["berserk_constructed", "Констракт", "berserk"],
  ["berserk_draft", "Драфт", "berserk"],
];

export const DISCIPLINE_NAME: Record<string, string> = {
  mtg_constructed: "Magic: констракт", mtg_draft: "Magic: драфт", mtg_edh: "Magic: EDH",
  berserk_constructed: "Берсерк: констракт", berserk_draft: "Берсерк: драфт",
};

export const TIERS: [string, string, string][] = [
  ["club", "Клубный", "Обычный турнир клуба"],
  ["city", "Городской", "Турнир для игроков всех клубов города"],
  ["open", "Открытый", "Приезжают игроки других городов: записываются по своему номеру, не вступая в клуб"],
  ["regional", "Региональный чемпионат", "Назначает администратор сайта"],
  ["pro", "Про-тур", "Назначает администратор сайта"],
];
export const TIER_NAME: Record<string, string> = Object.fromEntries(TIERS.map(([k, v]) => [k, v]));
export const ADMIN_TIERS = new Set(["regional", "pro"]);
