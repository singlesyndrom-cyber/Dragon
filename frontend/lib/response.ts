/** ККИ «Респонс»: фракции, подписи и данные карты (из backend/app/response.py). */
export type Rs = {
  factions?: string[]; types?: string[]; supertypes?: string[]; subtypes?: string[]; keywords?: string[];
  hero?: boolean; order?: boolean; legendary?: boolean; strength?: number | null; durability?: number | null;
  levels?: { influence: number | null; text: string | null }[]; rulings?: string[];
  printings?: { id: string; set: string; number: string; rarity: string; images: { face: string; medium: string | null; thumb: string | null }[] }[];
};

export const RS_FACTIONS = ["Порядок", "Хаос", "Жизнь", "Смерть", "Природа", "Технологии"];
export const RS_CREDIT = "Данные и изображения карт: «Респонс» (response-league.ru), с разрешения правообладателя.";
export const RS_SECTIONS: Record<string, string> = { commander: "Герой", orders: "Приказы", main: "Колода", side: "Дополнительная колода" };

export function rsImage(id?: string | null): string | null {
  return id ? `/api/img/rs/${id}` : null;
}
