/** Виды турниров для мастера создания: игра + формат + подсказка. */
export type Kind = { key: string; game: "mtg" | "berserk"; format: "swiss" | "fast_swiss" | "edh"; title: string; text: string; league: "edh" | "berserk" | null };

export const KINDS: Kind[] = [
  { key: "mtg-swiss", game: "mtg", format: "swiss", title: "Magic: швейцарская система",
    text: "Матчи один на один, туры по швейцарской системе, тайбрейки OWP и Buchholz.", league: null },
  { key: "mtg-edh", game: "mtg", format: "edh", title: "EDH: банк с таймером",
    text: "Столы по 3–5 человек, 70 минут, 7% банка соперников победителю. Можно привязать к сезону лиги.", league: "edh" },
  { key: "berserk-fast", game: "berserk", format: "fast_swiss", title: "Берсерк: быстрый швейцарец",
    text: "Короткий клубный вечер, обычно один тур. Очки 3/1/0 идут в сезон лиги.", league: "berserk" },
  { key: "berserk-swiss", game: "berserk", format: "swiss", title: "Берсерк: швейцарская система",
    text: "Полноценный турнир на несколько туров. Очки 3/1/0 идут в сезон лиги.", league: "berserk" },
];

export const DECK_POLICY: Record<string, string> = {
  none: "Не нужны", optional: "По желанию", required: "Обязательны",
};

export function kindOf(game: string, format: string): Kind | undefined {
  return KINDS.find((k) => k.game === game && k.format === format);
}
