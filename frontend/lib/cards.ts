/** Картотека: игры, подписи и примеры запросов. */

export type GameInfo = { code: string; title: string; short: string; examples: [string, string][] };

export const GAMES: GameInfo[] = [
  {
    code: "mtg", title: "Magic: The Gathering", short: "MTG",
    examples: [
      ["t:legendary t:creature id:bg", "Командиры в чёрно-зелёных цветах"],
      ["o:\"возьмите карту\" mv<=2", "Дешёвый добор (по русскому тексту)"],
      ["t:instant c:r o:damage f:pauper", "Красный урон для Pauper"],
      ["is:gamechanger", "Game Changers для брекетов EDH"],
      ["t:elf or t:goblin pow>=3", "Крупные эльфы и гоблины"],
      ["id<=wu t:artifact usd<1", "Бюджетные артефакты для бело-синей колоды"],
    ],
  },
  {
    code: "berserk", title: "Берсерк", short: "Берсерк",
    examples: [
      ["el:горы t:существо", "Существа стихии Горы"], ["класс:гном", "Все гномы"], ["t:летающее mv<=4", "Дешёвые летающие"],
      ["o:выстрел жизни>=6", "Стрелки с 6+ жизнями"], ["s:7 r:ультраредкая", "Ультраредкие «Гибели Богов»"],
      ["o:регенерация", "Карты с регенерацией"],
    ],
  },
];

GAMES.push({
  code: "response", title: "Респонс", short: "Респонс",
  examples: [
    ["фракция:хаос t:юнит", "Юниты Хаоса"], ["t:герой", "Все герои"], ["t:приказ фракция:природа", "Приказы Природы"],
    ["сила>=4 mv<=3", "Сильные дешёвые юниты"], ["o:натиск", "Карты с Натиском"], ["t:легендарный", "Легендарные карты"],
  ],
});

export function gameInfo(code: string): GameInfo {
  return GAMES.find((g) => g.code === code) || { code, title: code, short: code, examples: [] };
}

export const ORDER_LABELS: [string, string][] = [
  ["name", "по названию"], ["mv", "по мана-стоимости"], ["rarity", "по редкости"], ["color", "по числу цветов"],
  ["usd", "по цене, $"], ["eur", "по цене, €"], ["pow", "по силе"], ["tou", "по выносливости"], ["set", "по сету"],
];

export const RARITY_RU: Record<string, string> = {
  common: "обычная", uncommon: "необычная", rare: "редкая", mythic: "мифическая", special: "особая", bonus: "бонусная",
  ultra: "ультраредкая",
};

/** Значение в запросе: в кавычках, если есть пробелы. */
export function qv(v: string): string {
  return /[\s()]/.test(v) ? `"${v.replace(/"/g, "")}"` : v;
}

export function searchHref(q: string, game?: string | null): string {
  const p = new URLSearchParams({ q });
  if (game) p.set("game", game);
  return `/cards?${p}`;
}
