/** Картинки Scryfall - через наш сервер (/api/img): из России CDN Scryfall медленный, а сервер
 *  скачивает каждую картинку один раз и раздаёт из своего кэша. Остальные адреса не трогаем. */
const CARDS = "https://cards.scryfall.io/";
const SYMBOLS = "https://svgs.scryfall.io/card-symbols/";

export function viaSite(url?: string | null): string | null {
  if (!url) return null;
  if (url.startsWith(CARDS)) return "/api/img/" + url.slice(CARDS.length).split("?")[0];
  if (url.startsWith(SYMBOLS)) return "/api/img/symbol/" + url.slice(SYMBOLS.length).split("?")[0];
  return url;
}
