/** Конструктор колод: форматы, группировка по типам, статистика, экспорт. */

export const DECK_FORMATS: [string, string][] = [
  ["commander", "Commander (EDH)"], ["duel", "Duel Commander"], ["brawl", "Brawl"], ["standard", "Standard"],
  ["pioneer", "Pioneer"], ["modern", "Modern"], ["legacy", "Legacy"], ["vintage", "Vintage"], ["pauper", "Pauper"],
  ["casual", "Свободный"],
];
export const BK_FORMATS: [string, string][] = [
  ["berserk", "Констрактед (30–50, до 3 копий)"], ["berserk_limited", "Лимитед: драфт, силед"], ["casual", "Свободный"],
];
export const RS_FORMATS: [string, string][] = [
  ["response", "Дуэль (30 карт, до 2 копий, фракции героя)"], ["response_limited", "Драфт / силед (без ограничений)"], ["casual", "Свободный"],
];
export const formatsFor = (game: string) => game === "berserk" ? BK_FORMATS : game === "response" ? RS_FORMATS : DECK_FORMATS;
export const COMMANDER_FORMATS = new Set(["commander", "duel", "brawl"]);
export const formatTitle = (f: string) => [...DECK_FORMATS, ...BK_FORMATS, ...RS_FORMATS].find(([k]) => k === f)?.[1] || f;

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
  print?: { id: number; set: string; set_name?: string | null; number?: string | null } | null;
  bk?: import("./berserk").Bk; rs?: import("./response").Rs; text?: string | null;
};
export type Row = { key: string; name: string; qty: number; section: "main" | "side" | "commander" | "orders"; card: CardInfo | null };

export const GROUPS: [string, string][] = [
  ["commander", "Командир"], ["creature", "Существа"], ["planeswalker", "Planeswalker'ы"], ["battle", "Битвы"],
  ["instant", "Мгновенные"], ["sorcery", "Волшебство"], ["artifact", "Артефакты"], ["enchantment", "Чары"],
  ["land", "Земли"], ["flyer", "Летающие"], ["bk-artifact", "Артефакты"], ["terrain", "Местности"],
  ["orders", "Приказы"], ["rs-unit", "Юниты"], ["rs-spell", "Заклинания"], ["rs-boost", "Усиления"], ["rs-trap", "Ловушки"],
  ["rs-location", "Локации"],
  ["other", "Прочее"], ["side", "Сайдборд"],
];
const RS_GROUP: Record<string, string> = { "Юнит": "rs-unit", "Заклинание": "rs-spell", "Усиление": "rs-boost", "Ловушка": "rs-trap", "Локация": "rs-location" };

export function typeGroup(type?: string | null): string {
  const t = (type || "").split("//")[0].toLowerCase();
  // «Берсерк»: «Существо – Летающее · Класс», «Артефакт», «Местность»
  if (t.startsWith("существо")) return t.includes("летающ") ? "flyer" : "creature";
  if (t.startsWith("артефакт")) return "bk-artifact";
  if (t.startsWith("местность")) return "terrain";
  for (const g of ["creature", "planeswalker", "battle", "land", "instant", "sorcery", "artifact", "enchantment"]) {
    if (t.includes(g)) return g;
  }
  return "other";
}

export function rowGroup(r: Row): string {
  if (r.section === "commander") return "commander";
  if (r.section === "side") return "side";
  if (r.section === "orders") return "orders";
  if (r.card?.rs) return RS_GROUP[(r.card.rs.types || [])[0]] || "other";
  return typeGroup(r.card?.type);
}

/** Подписи разделов: у «Респонса» командир - герой, сайдборд - дополнительная колода. */
const RS_LABELS: Record<string, string> = { commander: "Герой", side: "Дополнительная колода" };

export function grouped(rows: Row[], game?: string): [string, string, Row[]][] {
  return GROUPS.map(([g, label]) => [g, (game === "response" && RS_LABELS[g]) || label, rows.filter((r) => rowGroup(r) === g)
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
  const elements: Record<string, number> = {};
  let mvSum = 0, spells = 0, usd = 0, eur = 0, elite = 0, isBk = false;
  for (const r of deck) {
    const bk = r.card?.bk;
    if (bk) {
      isBk = true;
      if (bk.elite) elite += r.qty;
      for (const el of bk.elements || []) elements[el] = (elements[el] || 0) + r.qty;
    }
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
  return { curve, pips, types, avg: spells ? mvSum / spells : 0, usd, eur, lands: types.land || 0, elements, elite, isBk };
}

/** Экспорт: «Commander / Deck / Sideboard» понимают Moxfield, MTGGoldfish, Arena; MTGO - основа, пустая строка, сайд.
 *  withPrints: выбранные издания как в Moxfield - «1 Sol Ring (CMM) 410». */
/** Код карты «Берсерка» в формате NXT: выпуск × 10000 + номер (только для номерных выпусков 1–8). */
export function nxtCode(r: Row): number | null {
  const set = Number(r.card?.set), num = Number(r.card?.bk?.number);
  return r.card?.bk && Number.isInteger(set) && set > 0 && Number.isInteger(num) && num > 0 ? set * 10000 + num : null;
}

export function exportText(rows: Row[], style: "text" | "mtgo" | "nxt", withPrints = false): string {
  if (rows.some((r) => r.section === "orders" || r.card?.rs)) {        // «Респонс»: герой, приказы, колода, доп. колода
    const sec = (s: string) => rows.filter((r) => r.section === s).map((r) => `${r.qty} ${r.card?.name || r.name}`);
    return ([["Герой", "commander"], ["Приказы", "orders"], ["Колода", "main"], ["Дополнительная колода", "side"]] as const)
      .filter(([, s]) => sec(s).length).map(([t, s]) => `${t}\n${sec(s).join("\n")}`).join("\n\n") + "\n";
  }
  if (style === "nxt") {
    return rows.filter((r) => r.section !== "side").map((r) => {
      const code = nxtCode(r);
      return code ? `${r.qty} ${code}` : `# ${r.qty} ${r.card?.name || r.name} — нет кода NXT`;
    }).join("\n") + "\n";
  }
  const ed = (r: Row) => withPrints && style === "text" && r.card?.print
    ? ` (${r.card.print.set.toUpperCase()})${r.card.print.number ? ` ${r.card.print.number}` : ""}` : "";
  const line = (r: Row) => `${r.qty} ${r.card?.name || r.name}${ed(r)}`;
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
