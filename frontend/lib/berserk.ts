/** «Берсерк» (классика): значки в тексте карт, стихии, подписи. Данные карт - ProBerserk.ru. */

export const BK_ICON_RU: Record<string, string> = {
  tap: "Закрыть", counter: "Фишка", strike: "Удар", health: "Здоровье", move: "Движение", armor: "Броня",
  regen: "Регенерация", ova: "Опыт в атаке", ovz: "Опыт в защите", ovs: "Опыт в стрельбе",
  elite: "Элитная", ordinary: "Рядовая",
};

export const ELEMENTS = ["Степи", "Горы", "Леса", "Болота", "Тьма", "Нейтральная"];

export type Bk = {
  number?: string; elements?: string[]; elite?: boolean; unique?: boolean; class?: string | null; kind?: string;
  health?: number | null; move?: number | null; strike?: string | null; icons?: Record<string, number | boolean>;
};

export const bkIconUrl = (token: string) => `/api/img/bk/icons/icon-${token}.png`;

export function bkCost(c: { mana_cost?: string | null; bk?: Bk }): string {
  if (!c.bk) return c.mana_cost || "";
  return `${c.mana_cost ?? ""}${c.bk.elite ? " элит." : ""}`;
}

export const BK_CREDIT = "Данные карт «Берсерка» — ProBerserk.ru. Права на игру и изображения — «Мир Хобби».";
