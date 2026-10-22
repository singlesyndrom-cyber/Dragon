import Link from "next/link";
import { searchHref } from "@/lib/cards";

export const metadata = { title: "Синтаксис поиска — Картотека" };

const ROWS: [string, string, string[]][] = [
  ["Название", "Слова без ключа ищутся в названии — английском или русском, в любом порядке. Точное название — через !\"…\".",
    ["сол кольцо", "lightning bolt", "!\"Sol Ring\""]],
  ["t: тип", "Тип и подтип карты, по-английски или по-русски.", ["t:legendary t:creature", "t:эльф", "t:\"artifact creature\""]],
  ["o: текст", "Текст правил. Фразу берите в кавычки.", ["o:\"возьмите карту\"", "o:flying", "o:\"deals 3 damage\""]],
  ["c: цвет", "Цвета карты: w u b r g. c:rg — красная и зелёная (может быть и другие цвета), c=rg — ровно эти, c<=rg — не больше этих. c:c — бесцветная, c:m — многоцветная. Понимает названия гильдий: c:izzet.",
    ["c:r", "c=wu", "c<=bg", "c:m", "c:golgari"]],
  ["id: идентичность", "Цветовая идентичность в пределах — карта подходит в колоду командира этих цветов.", ["id:wub t:creature", "id<=g"]],
  ["mv: стоимость", "Мана-стоимость (cmc). Сравнения: = < <= > >= !=.", ["mv<=2", "mv=0 t:artifact"]],
  ["pow: tou: loy:", "Сила, выносливость, верность. Карты со «*» в числовые сравнения не попадают.", ["pow>=5", "tou<2 t:creature", "loy>=4"]],
  ["r: редкость", "common, uncommon, rare, mythic. Сравнения тоже работают.", ["r:mythic", "r>=rare"]],
  ["s: сет", "Код сета, как на карте.", ["s:cmm", "s:dmu t:legendary"]],
  ["f: формат", "Разрешена в формате. banned: — запрещена, restricted: — ограничена. Форматы: commander, standard, pioneer, modern, legacy, vintage, pauper, duel, brawl.",
    ["f:pauper c:u", "banned:commander", "restricted:vintage"]],
  ["is:", "gamechanger (gc) — список Game Changers; commander — может быть командиром; dfc — двусторонняя; russian — есть русское название; vanilla — без текста.",
    ["is:gc", "is:commander id:r", "is:dfc", "is:vanilla"]],
  ["kw: a:", "Ключевое слово и художник.", ["kw:flying kw:lifelink", "a:\"john avon\""]],
  ["usd: eur:", "Цена по данным Scryfall.", ["usd<1 f:commander", "eur>=20"]],
  ["Отрицание", "Минус перед условием исключает такие карты.", ["t:creature -t:legendary", "-c:b f:modern"]],
  ["or и скобки", "Условия через пробел — «и». or (или «или») — «или»; скобки группируют.", ["t:elf or t:goblin", "(c:r or c:g) mv<=2"]],
  ["Сортировка", "order: name, mv, rarity, color, usd, eur, pow, tou, set; dir:desc — по убыванию.", ["t:dragon order:mv dir:desc"]],
  ["*", "Все карты игры — удобно сочетать с сортировкой.", ["* order:usd dir:desc"]],
];

export default function Syntax() {
  return (
    <div className="syntax">
      <p className="muted small"><Link href="/cards">← Картотека</Link></p>
      <h1>Синтаксис поиска</h1>
      <p className="lead">
        Запрос состоит из условий через пробел — карта должна подходить под все. Ключи пишутся и по-русски:
        тип:, текст:, цвет:, ид:, мв:, сила:, редкость:, сет:, формат:, есть:, художник:. Если условие не понято,
        над результатами появится подсказка. Язык похож на Scryfall, так что привычные запросы оттуда работают.
      </p>
      <div className="table-wrap section">
        <table>
          <thead><tr><th>Условие</th><th>Что ищет</th><th>Примеры</th></tr></thead>
          <tbody>
            {ROWS.map(([key, what, ex]) => (
              <tr key={key}>
                <td style={{ whiteSpace: "nowrap" }}><b>{key}</b></td>
                <td className="small">{what}</td>
                <td className="small">{ex.map((q) => <div key={q}><Link href={searchHref(q, "mtg")}><code>{q}</code></Link></div>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Для «Берсерка» и других игр работают название, t:, o:, mv:, r:, s: — остальные поля есть только у Magic.</p>
    </div>
  );
}
