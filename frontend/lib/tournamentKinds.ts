/** Виды турниров для мастера создания: игра + формат + подсказка. */
export type Kind = { key: string; game: "mtg" | "berserk"; format: "swiss" | "fast_swiss" | "edh"; title: string; text: string;
  league: "edh" | "berserk" | null; draft?: boolean };

export const KINDS: Kind[] = [
  { key: "mtg-swiss", game: "mtg", format: "swiss", title: "Magic: швейцарская система",
    text: "Матчи один на один, туры по швейцарской системе, тайбрейки OWP и Buchholz.", league: null },
  { key: "mtg-edh", game: "mtg", format: "edh", title: "EDH: банк с таймером",
    text: "Столы по 3–5 человек, 70 минут, 7% банка соперников победителю. Можно привязать к сезону лиги.", league: "edh" },
  { key: "mtg-draft", game: "mtg", format: "swiss", draft: true, title: "Magic: бустерный драфт",
    text: "Рассадка по столам, таймеры пиков по MTR, 25 минут на сборку, туры по 50 минут; первый тур — с сидящим напротив.", league: null },
  { key: "berserk-fast", game: "berserk", format: "fast_swiss", title: "Берсерк: быстрый швейцарец",
    text: "Короткий клубный вечер, обычно один тур. Очки 3/1/0 идут в сезон лиги.", league: "berserk" },
  { key: "berserk-swiss", game: "berserk", format: "swiss", title: "Берсерк: швейцарская система",
    text: "Полноценный турнир на несколько туров. Очки 3/1/0 идут в сезон лиги.", league: "berserk" },
  { key: "berserk-draft", game: "berserk", format: "swiss", draft: true, title: "Берсерк: драфт",
    text: "Драфт на трёх бустерах (например, 7-8-8): рассадка, таймеры пиков, сборка колоды, туры по 50 минут.", league: "berserk" },
];

export const DECK_POLICY: Record<string, string> = {
  none: "Не нужны", optional: "По желанию", required: "Обязательны",
};

export function kindOf(game: string, format: string, draft = false): Kind | undefined {
  return KINDS.find((k) => k.game === game && k.format === format && !!k.draft === !!draft);
}
