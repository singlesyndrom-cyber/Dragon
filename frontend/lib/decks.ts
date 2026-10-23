/** Конструктор колод: форматы, группировка по типам, статистика, экспорт. */

export const DECK_FORMATS: [string, string][] = [
  ["commander", "Commander (EDH)"], ["duel", "Duel Commander"], ["brawl", "Brawl"], ["standard", "Standard"],
  ["pioneer", "Pioneer"], ["modern", "Modern"], ["legacy", "Legacy"], ["vintage", "Vintage"], ["pauper", "Pauper"],
  ["casual", "Свободный"],
];
export const COMMANDER_FORMATS = new Set(["commander", "duel", "brawl"]);
export const formatTitle = (f: string) => DECK_FORMATS.find(([k]) => k === f)?.[1] || f;

export const VISIBILITY: [string, string, string][] = [
  ["private", "Личная", "Видите только вы и организатор турнира, если подадите колоду"],
  ["link", "По ссылке", "Видит тот, кому вы дали ссылку"],
  ["public", "Публичная", "Колода в каталоге сайта, с вашим ником"],
];

export type CardInfo = {
  id: number; name: string; name_ru?: string | null; type?: string | null; type_ru?: string | null;
  mana_cost?: string | null; cmc?: number | null; colors?: string[]; color_identity?: string[];
  rarity?: string | null; set?: string | null; image_url?: string | null; image_large?: string | null;
  prices?: Record<string, string | null>; legalities?: Record<string, string>; is_game_changer?: boolean;
  back_image?: string | null;
};
export type Row = { key: string; name: string; qty: number; section: "main" | "side" | "commander"; card: CardInfo | null };

export const GROUPS: [string, string][] = [
  ["commander", "Командир"], ["creature", "Существа"], ["planeswalker", "Planeswalker'ы"], ["battle", "Битвы"],
  ["instant", "Мгновенные"], ["sorcery", "Волшебство"], ["artifact", "Артефакты"], ["enchantment", "Чары"],
  ["land", "Земли"], ["other", "Прочее"], ["side", "Сайдборд"],
];

export function typeGroup(type?: string | null): string {
  const t = (type || "").split("//")[0].toLowerCase();
  for (const g of ["creature", "planeswalker", "battle", "land", "instant", "sorcery", "artifact", "enchantment"]) {
    if (t.includes(g)) return g;
  }
  return "other";
}

export function rowGroup(r: Row): string {
  if (r.section === "commander") return "commander";
  if (r.section === "side") return "side";
  return typeGroup(r.card?.type);
}

export function grouped(rows: Row[]): [string, string, Row[]][] {
  return GROUPS.map(([g, label]) => [g, label, rows.filter((r) => rowGroup(r) === g)
    .sort((a, b) => (a.card?.cmc ?? 99) - (b.card?.cmc ?? 99) || a.name.localeCompare(b.name))] as [string, string, Row[]])
    .filter(([, , rs]) => rs.length);
}

export const count = (rows: Row[]) => rows.reduce((n, r) => n + r.qty, 0);
export const playing = (rows: Row[]) => rows.filter((r) => r.section !== "side");

export function stats(rows: Row[]) {
  const deck = playing(rows);
  const curve = Array(8).fill(0) as number[];         // 0..6, 7+ - без земель
  const pips: Record<string, number> = { W: 0, U: 0, B: 0, R: 0, G: 0, C: 0 };
  const types: Record<string, number> = {};
  let mvSum = 0, spells = 0, usd = 0, eur = 0;
  for (const r of deck) {
    const g = typeGroup(r.card?.type);
    types[g] = (types[g] || 0) + r.qty;
    if (g !== "land") {
      const mv = Math.round(r.card?.cmc ?? 0);
      curve[Math.min(mv, 7)] += r.qty;
      mvSum += (r.card?.cmc ?? 0) * r.qty;
      spells += r.qty;
    }
    for (const m of (r.card?.mana_cost || "").matchAll(/\{([^}]+)\}/g)) {
      for (const c of ["W", "U", "B", "R", "G", "C"]) if (m[1].toUpperCase().split("/").includes(c)) pips[c] += r.qty;
    }
  }
  for (const r of rows) {
    const p = r.card?.prices || {};
    if (p.usd) usd += Number(p.usd) * r.qty;
    if (p.eur) eur += Number(p.eur) * r.qty;
  }
  return { curve, pips, types, avg: spells ? mvSum / spells : 0, usd, eur, lands: types.land || 0 };
}

/** Экспорт: «Commander / Deck / Sideboard» понимают Moxfield, MTGGoldfish, Arena; MTGO - основа, пустая строка, сайд. */
export function exportText(rows: Row[], style: "text" | "mtgo"): string {
  const line = (r: Row) => `${r.qty} ${r.card?.name || r.name}`;
  const by = (s: string) => rows.filter((r) => r.section === s).map(line);
  if (style === "mtgo") {
    return [...by("commander"), ...by("main")].join("\n") + (by("side").length ? "\n\n" + by("side").join("\n") : "") + "\n";
  }
  const parts: string[] = [];
  if (by("commander").length) parts.push("Commander\n" + by("commander").join("\n"));
  parts.push("Deck\n" + by("main").join("\n"));
  if (by("side").length) parts.push("Sideboard\n" + by("side").join("\n"));
  return parts.join("\n\n") + "\n";
}

export function fromApi(cards: any[]): Row[] {
  return cards.map((c, i) => ({ key: `${c.card?.id ?? c.name}-${c.section}-${i}`, name: c.name, qty: c.qty,
    section: c.section, card: c.card }));
}

export function displayName(r: Row, lang: "ru" | "en"): string {
  return lang === "ru" ? r.card?.name_ru || r.card?.name || r.name : r.card?.name || r.name;
}

export function shuffle<T>(xs: T[]): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
