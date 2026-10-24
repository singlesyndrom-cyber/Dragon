/** Главная: игра, подписи турниров, дни недели. Всё время - по часовому поясу клуба (TZ). */
import { FORMATS, plural, TZ } from "./format";

export type HomeGame = "mtg" | "berserk" | "response";
export const HOME_GAMES: [HomeGame, string][] = [["mtg", "Magic"], ["berserk", "Берсерк"], ["response", "Респонс"]];
export const GAME_COOKIE = "home-game";

export function homeGame(v?: string | null): HomeGame | null {
  return v === "mtg" || v === "berserk" || v === "response" ? v : null;
}

export type HomeEvent = {
  id: number; name: string; club: string | null; club_slug: string | null; game: string; format: string;
  status: "registration" | "running" | "finished"; starts_at: string; players: number | null; round: number;
  rounds_total: number | null; max_players: number | null; draft: boolean; draft_sets: string | null;
  deck_policy?: string; deck_id?: number | null; deck_name?: string | null;
};

const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

/** «2026-10-23» по местному времени клуба. */
export function dayKey(v: string | Date): string {
  return dayKeyFmt.format(typeof v === "string" ? new Date(v) : v);
}

export function timeOf(v: string): string {
  return new Date(v).toLocaleTimeString("ru-RU", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
}

/** «Сегодня», «Завтра» или «Сб, 24». */
export function dayLabel(v: string, now: string): string {
  const k = dayKey(v);
  if (k === dayKey(now)) return "Сегодня";
  if (k === dayKey(new Date(new Date(now).getTime() + 86400000))) return "Завтра";
  const d = new Date(v);
  const wd = d.toLocaleDateString("ru-RU", { timeZone: TZ, weekday: "short" });
  return `${wd[0].toUpperCase()}${wd.slice(1)}, ${d.toLocaleDateString("ru-RU", { timeZone: TZ, day: "numeric" })}`;
}

/** Семь дней начиная с сегодняшнего: ключ, день недели, число. */
export function weekDays(now: string): { key: string; wd: string; num: string }[] {
  const base = new Date(now).getTime();
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(base + i * 86400000);
    const wd = d.toLocaleDateString("ru-RU", { timeZone: TZ, weekday: "short" });
    return { key: dayKey(d), wd: i === 0 ? "Сегодня" : wd[0].toUpperCase() + wd.slice(1),
             num: d.toLocaleDateString("ru-RU", { timeZone: TZ, day: "numeric" }) };
  });
}

/** «Драфт 7-8-8», «Быстрый швейцарец», «EDH, банк с таймером». */
export function formatLabel(t: Pick<HomeEvent, "format" | "draft" | "draft_sets">): string {
  if (t.draft) return t.draft_sets ? `Драфт ${t.draft_sets}` : "Драфт";
  return FORMATS[t.format] || t.format;
}

/** Метка идущего турнира: «Идёт тур 3 из 4», «Идёт драфт». */
export function liveLabel(t: HomeEvent): string {
  if (t.round > 0) return t.rounds_total ? `Идёт тур ${t.round} из ${t.rounds_total}` : `Идёт тур ${t.round}`;
  return t.draft ? "Идёт драфт" : "Идёт";
}

export function seatsLabel(t: HomeEvent): string {
  const n = t.players ?? 0;
  if (t.max_players) return `${n} из ${t.max_players} мест`;
  return `${n} ${plural(n, "игрок", "игрока", "игроков")}`;
}

/** Заполненность в процентах для полоски; без лимита мест - null. */
export function fill(t: HomeEvent): number | null {
  if (!t.max_players) return null;
  return Math.min(100, Math.round(((t.players ?? 0) / t.max_players) * 100));
}
