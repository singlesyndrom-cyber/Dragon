/** Картинки Scryfall - через наш сервер (/api/img): из России CDN Scryfall медленный, а сервер
 *  скачивает каждую картинку один раз и раздаёт из своего кэша. Остальные адреса не трогаем. */
const CARDS = "https://cards.scryfall.io/";
const SYMBOLS = "https://svgs.scryfall.io/card-symbols/";
const PROBERSERK = "https://proberserk.ru/images/";
const RESPONSE = "https://response-league.ru/api/v1/card-images/";

export function viaSite(url?: string | null): string | null {
  if (!url) return null;
  if (url.startsWith(CARDS)) return "/api/img/" + url.slice(CARDS.length).split("?")[0];
  if (url.startsWith(PROBERSERK)) return "/api/img/bk/" + url.slice(PROBERSERK.length).split("?")[0];
  if (url.startsWith(RESPONSE)) return "/api/img/rs/" + url.slice(RESPONSE.length).split("?")[0];
  if (url.startsWith(SYMBOLS)) return "/api/img/symbol/" + url.slice(SYMBOLS.length).split("?")[0];
  return url;
}
