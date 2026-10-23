export const GAMES: Record<string, string> = { mtg: "Magic: The Gathering", berserk: "Берсерк" };

export const FORMATS: Record<string, string> = {
  swiss: "Швейцарская система",
  fast_swiss: "Быстрый швейцарец",
  edh: "EDH, банк с таймером",
};

export const T_STATUS: Record<string, string> = {
  registration: "Идёт регистрация",
  running: "Идёт игра",
  finished: "Завершён",
};

export const CONDITIONS: Record<string, string> = {
  NM: "Near Mint",
  LP: "Lightly Played",
  MP: "Moderately Played",
  HP: "Heavily Played",
  DMG: "Damaged",
};

export const WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"];

export const TZ = "Europe/Moscow";

export function dateTime(v?: string | null): string {
  if (!v) return "—";
  return new Date(v).toLocaleString("ru-RU", {
    timeZone: TZ, day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });
}

export function dateOnly(v?: string | null): string {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("ru-RU", { timeZone: TZ, day: "numeric", month: "long", year: "numeric" });
}

export function rub(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("ru-RU") + " ₽";
}

export function signed(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  const r = Math.round(n * 10) / 10;
  return (r > 0 ? "+" : "") + r.toLocaleString("ru-RU");
}

export function pct(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  return (n * 100).toFixed(1).replace(".", ",") + "%";
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
