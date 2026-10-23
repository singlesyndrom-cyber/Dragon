/** «Берсерк» (классика): значки в тексте карт, стихии, подписи. Данные карт - ProBerserk.ru. */

// Названия значков - по «Расширенным правилам» 6.1-1, раздел «Символы»; коды - как на ProBerserk.ru
export const BK_ICON_RU: Record<string, string> = {
  health: "Жизни", move: "Запас движения", strike: "Простой удар", uchr: "Удар через ряд (УЧР)",
  tap: "Закрытие карты (действие)", counter: "Фишка", instant: "Внезапная особенность",
  first: "Если вы ходите первым", second: "Если вы ходите вторым",
  zom: "Защита от магии (ЗОМ)", zor: "Защита от разрядов (ЗОР)", zoz: "Защита от заклинаний (ЗОЗ)",
  zov: "Защита от выстрелов (ЗОВ)", zot: "Защита от метаний (ЗОМет)", zoal: "Защита от атак летающих",
  zoo: "Защита от отравления (ЗОЯ)", direct: "Направленный удар (НУ)", regen: "Регенерация", stamina: "Стойкость",
  armor: "Броня", ova: "Опыт в атаке", ovz: "Опыт в защите", ovs: "Опыт в стрельбе",
  wolf: "Оборотень (волк)", human: "Оборотень (человек)", elite: "Элитная", ordinary: "Рядовая",
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
