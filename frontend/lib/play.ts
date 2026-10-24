/** Приложение за столом: текущий матч в турнире и набор отряда «Берсерка» по кристаллам.
 *  Правила набора - Расширенные правила 6.1-1, п. 402-403. */

export type Outcome = "win" | "loss" | "draw";
export type MyReport = { outcome: Outcome; score: string | null; source: string; at: string } | null;
export type Tourn = { id: number; name: string; game: string; format: string; club: string; round: number; rounds_total: number | null };
export type EdhSays = { outcome: "win" | "draw"; winner_id: number | null; winner: string | null; source: string; at: string };
export type CurrentEdh = {
  kind: "edh"; tournament: Tourn; table_id: number; table: number; bracket: number; status: "playing" | "finished";
  seconds_left: number; seats: { user_id: number; nickname: string; player_no: number | null; me: boolean }[];
  outcome: string | null; winner: string | null; my_report: EdhSays | null; reports: (EdhSays & { nickname: string })[];
};
export type CurrentMatch = {
  kind: "match";
  tournament: { id: number; name: string; game: string; format: string; club: string; round: number; rounds_total: number | null };
  match_id: number; table: number; side: "p1" | "p2"; bye: boolean;
  opponent: { nickname: string; player_no: number | null; is_guest: boolean; rating: { rating: number; games: number } | null } | null;
  result: Outcome | null; my_report: MyReport; opp_report: MyReport;
};
export type Current = CurrentMatch | CurrentEdh;

export const OUTCOME_RU: Record<Outcome, string> = { win: "победа", loss: "поражение", draw: "ничья" };

/** Счёт партий «мои-соперника[-ничьи]» -> исход матча. */
export function outcomeOf(score: [number, number, number]): Outcome {
  const [w, l] = score;
  return w > l ? "win" : l > w ? "loss" : "draw";
}
export function scoreText([w, l, d]: [number, number, number]): string {
  return d ? `${w}-${l}-${d}` : `${w}-${l}`;
}

// ---------------- «Берсерк»: набор отряда ----------------
export const BK_GOLD = 24;
export const BK_SILVER = 22;
export const BK_FLY_LIMIT = 15;
export const BK_CELLS = 15;
export const NEUTRAL = "Нейтральная";

export type SquadCard = {
  key: string; name: string; cost: number; elite: boolean; unique: boolean; elements: string[];
  creature: boolean; flying: boolean; image?: string | null;
};

export type SquadState = {
  second: boolean;      // ходит вторым: +1 золотой и +1 серебряный
  mulligans: number;    // пересдачи: -1 золотой за каждую
  bonusGold: number;    // ручная поправка (особенности карт «при наборе», например +2 золотых)
  bonusSilver: number;
  cells: number;        // клеток для расстановки (обычно 15)
  squad: SquadCard[];
};

export const EMPTY_SQUAD: SquadState = { second: false, mulligans: 0, bonusGold: 0, bonusSilver: 0, cells: BK_CELLS, squad: [] };

export type SquadSummary = {
  gold0: number; silver0: number; goldLeft: number; silverLeft: number;
  eliteCost: number; ordinaryCost: number; penalty: number; elements: string[]; flyCost: number;
  problems: string[]; warnings: string[];
};

/** Сколько кристаллов осталось и что нарушено. Кристаллы одного цвета взаимозаменяемы, поэтому оплата считается
 *  выгоднейшим способом: элитные - только золотом, рядовые - сначала серебром, остаток - золотом. */
export function squadSummary(s: SquadState): SquadSummary {
  const gold0 = BK_GOLD + (s.second ? 1 : 0) - s.mulligans + s.bonusGold;
  const silver0 = BK_SILVER + (s.second ? 1 : 0) + s.bonusSilver;
  const elements: string[] = [];
  let eliteCost = 0, ordinaryCost = 0, flyCost = 0;
  for (const c of s.squad) {
    if (c.elite) eliteCost += c.cost; else ordinaryCost += c.cost;
    if (c.flying) flyCost += c.cost;
    for (const e of c.elements) if (e !== NEUTRAL && !elements.includes(e)) elements.push(e);
  }
  const penalty = Math.max(0, elements.length - 1);       // штраф 1 золотой за каждую новую стихию, кроме первой
  const silverLeft = Math.max(0, silver0 - ordinaryCost);
  const goldLeft = gold0 - eliteCost - penalty - Math.max(0, ordinaryCost - silver0);
  const problems: string[] = [];
  if (goldLeft < 0) problems.push(`Не хватает золота: ${-goldLeft}`);
  if (flyCost > BK_FLY_LIMIT) problems.push(`Летающие стоят ${flyCost} — можно не больше ${BK_FLY_LIMIT} кристаллов`);
  if (s.squad.length > s.cells) problems.push(`Карт ${s.squad.length}, а клеток для расстановки ${s.cells}`);
  const seen = new Set<string>();
  for (const c of s.squad) {
    if (!c.unique) continue;
    const n = c.name.toLowerCase();
    if (seen.has(n)) problems.push(`Уникальная карта дважды: ${c.name}`);
    seen.add(n);
  }
  const warnings: string[] = [];
  if (s.squad.length && !s.squad.some((c) => c.creature)) warnings.push("В отряде должно быть хотя бы одно существо");
  return { gold0, silver0, goldLeft, silverLeft, eliteCost, ordinaryCost, penalty, elements, flyCost, problems, warnings };
}

/** Можно ли взять карту: проверка будущего состояния отряда (п. 403.2.3.1). Пустой список - можно. */
export function canTake(s: SquadState, c: SquadCard): string[] {
  return squadSummary({ ...s, squad: [...s.squad, c] }).problems;
}

/** Пересдача стоит 1 золотой; без золота заявить её - проиграть (п. 402.4). */
export function canMulligan(s: SquadState): boolean {
  return squadSummary({ ...s, squad: [] }).gold0 > 0;
}

/** Карта колоды/поиска -> карта для набора. Летающие в базе ProBerserk помечены запасом движения 0. */
export function toSquadCard(card: any, key: string): SquadCard | null {
  const bk = card?.bk;
  if (!bk) return null;
  const cost = parseInt(card.mana_cost ?? "", 10);
  const creature = (bk.kind || "").toLowerCase().startsWith("существо");
  return {
    key, name: card.name_ru || card.name, cost: Number.isFinite(cost) ? cost : 0, elite: !!bk.elite, unique: !!bk.unique,
    elements: bk.elements || [], creature, flying: creature && bk.move === 0, image: card.image_url ?? null,
  };
}
