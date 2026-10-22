"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import Mana from "@/components/Mana";
import { api } from "@/lib/api";
import { GAMES, ORDER_LABELS, qv, searchHref } from "@/lib/cards";

const COLORS = ["W", "U", "B", "R", "G", "C"];
const OPS: [string, string][] = [["=", "="], ["<", "<"], ["<=", "≤"], [">", ">"], [">=", "≥"], ["!=", "≠"]];
const RARITIES: [string, string][] = [["common", "Обычная"], ["uncommon", "Необычная"], ["rare", "Редкая"], ["mythic", "Мифическая"]];
const FORMATS: [string, string][] = [["commander", "Commander"], ["standard", "Standard"], ["pioneer", "Pioneer"],
  ["modern", "Modern"], ["legacy", "Legacy"], ["vintage", "Vintage"], ["pauper", "Pauper"], ["duel", "Duel Commander"], ["brawl", "Brawl"]];

type Num = { op: string; v: string };
const num0: Num = { op: "=", v: "" };

function words(field: string, key: string): string[] {
  // «летающий дракон» -> t:летающий t:дракон; фраза в кавычках остаётся фразой
  const out: string[] = [];
  const re = /"([^"]+)"|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(field))) out.push(`${key}:${qv(m[1] ?? m[2])}`);
  return out;
}

function NumField({ id, value, set }: { id: string; value: Num; set: (n: Num) => void }) {
  return (
    <span className="row" style={{ gap: 6 }}>
      <select value={value.op} onChange={(e) => set({ ...value, op: e.target.value })} aria-label="Сравнение" style={{ width: 70 }}>
        {OPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <input id={id} inputMode="decimal" value={value.v} onChange={(e) => set({ ...value, v: e.target.value })} style={{ width: 100 }} />
    </span>
  );
}

function Advanced() {
  const router = useRouter();
  const params = useSearchParams();
  const [game, setGame] = useState(params.get("game") || "mtg");
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [type, setType] = useState("");
  const [colors, setColors] = useState<string[]>([]);
  const [colorMode, setColorMode] = useState(">=");
  const [ident, setIdent] = useState<string[]>([]);
  const [mv, setMv] = useState<Num>(num0);
  const [pow, setPow] = useState<Num>(num0);
  const [tou, setTou] = useState<Num>(num0);
  const [rar, setRar] = useState<string[]>([]);
  const [set, setSet] = useState("");
  const [sets, setSets] = useState<any[]>([]);
  const [fmt, setFmt] = useState("");
  const [fmtStatus, setFmtStatus] = useState("f");
  const [gc, setGc] = useState(false);
  const [ru, setRu] = useState(false);
  const [artist, setArtist] = useState("");
  const [usd, setUsd] = useState<Num>({ op: "<=", v: "" });
  const [order, setOrder] = useState("name");
  const mtg = game === "mtg";

  useEffect(() => { api<any[]>(`/cards/sets?game=${game}`).then(setSets).catch(() => setSets([])); setSet(""); }, [game]);

  function toggle(list: string[], v: string, put: (l: string[]) => void) {
    put(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  }

  function build(): string {
    const q: string[] = [];
    q.push(...words(name, "name").map((w) => w.replace(/^name:/, "")));
    q.push(...words(text, "o"), ...words(type, "t"));
    if (colors.length) q.push(`c${colorMode === ":" ? ">=" : colorMode}${colors.includes("C") ? "c" : colors.join("").toLowerCase()}`);
    if (ident.length) q.push(`id<=${ident.includes("C") ? "c" : ident.join("").toLowerCase()}`);
    for (const [k, n] of [["mv", mv], ["pow", pow], ["tou", tou], ["usd", usd]] as [string, Num][]) {
      if (n.v.trim()) q.push(`${k}${n.op}${n.v.trim().replace(",", ".")}`);
    }
    if (rar.length === 1) q.push(`r:${rar[0]}`);
    else if (rar.length > 1) q.push(`(${rar.map((r) => `r:${r}`).join(" or ")})`);
    if (set) q.push(`s:${set}`);
    if (fmt) q.push(`${{ f: "f", banned: "banned", restricted: "restricted" }[fmtStatus]}:${fmt}`);
    if (gc) q.push("is:gamechanger");
    if (ru) q.push("is:russian");
    if (artist.trim()) q.push(`a:${qv(artist.trim())}`);
    if (order !== "name") q.push(`order:${order}`);
    return q.join(" ");
  }

  const query = build();
  function submit(e: FormEvent) {
    e.preventDefault();
    router.push(searchHref(query || "*", game));
  }

  return (
    <>
      <p className="muted small"><Link href={`/cards?game=${game}`}>← Картотека</Link></p>
      <h1>Расширенный поиск</h1>
      <p className="lead">Заполните нужные поля — форма соберёт запрос. Его можно поправить вручную в строке поиска; правила — в <Link href="/cards/syntax">синтаксисе</Link>.</p>
      <form onSubmit={submit} className="adv section">
        <label htmlFor="a-game">Игра</label>
        <select id="a-game" value={game} onChange={(e) => setGame(e.target.value)} style={{ width: "auto" }}>
          {GAMES.map((g) => <option key={g.code} value={g.code}>{g.title}</option>)}
        </select>

        <label htmlFor="a-name">Название</label>
        <input id="a-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Любые слова из названия, по-русски или по-английски" />

        <label htmlFor="a-text">Текст</label>
        <input id="a-text" value={text} onChange={(e) => setText(e.target.value)} placeholder='Например: "возьмите карту" или flying' />

        <label htmlFor="a-type">Тип</label>
        <input id="a-type" value={type} onChange={(e) => setType(e.target.value)} placeholder="Например: legendary creature, дракон" />

        {mtg ? (
          <>
            <label>Цвета</label>
            <div className="colors row">
              {COLORS.map((c) => (
                <label key={c}><input type="checkbox" checked={colors.includes(c)} onChange={() => toggle(colors, c, setColors)} />
                  <Mana text={`{${c}}`} size={20} /></label>
              ))}
              <select value={colorMode} onChange={(e) => setColorMode(e.target.value)} aria-label="Как сравнивать цвета" style={{ width: "auto" }}>
                <option value=">=">включает эти цвета</option>
                <option value="=">ровно эти цвета</option>
                <option value="<=">не больше этих цветов</option>
              </select>
            </div>

            <label>Командир</label>
            <div className="colors row">
              {COLORS.map((c) => (
                <label key={c}><input type="checkbox" checked={ident.includes(c)} onChange={() => toggle(ident, c, setIdent)} />
                  <Mana text={`{${c}}`} size={20} /></label>
              ))}
              <span className="muted small">цветовая идентичность — карта подходит в колоду такого командира</span>
            </div>
          </>
        ) : null}

        <label htmlFor="a-mv">Мана-стоимость</label>
        <NumField id="a-mv" value={mv} set={setMv} />

        {mtg ? (
          <>
            <label htmlFor="a-pow">Сила</label>
            <NumField id="a-pow" value={pow} set={setPow} />
            <label htmlFor="a-tou">Выносливость</label>
            <NumField id="a-tou" value={tou} set={setTou} />
          </>
        ) : null}

        <label>Редкость</label>
        <div className="colors row">
          {RARITIES.map(([k, l]) => (
            <label key={k}><input type="checkbox" checked={rar.includes(k)} onChange={() => toggle(rar, k, setRar)} /> {l}</label>
          ))}
        </div>

        <label htmlFor="a-set">Сет</label>
        <select id="a-set" value={set} onChange={(e) => setSet(e.target.value)}>
          <option value="">Любой</option>
          {sets.map((s) => <option key={s.code} value={s.code}>{s.name} ({s.code.toUpperCase()}, {s.cards})</option>)}
        </select>

        {mtg ? (
          <>
            <label htmlFor="a-fmt">Формат</label>
            <span className="row" style={{ gap: 6 }}>
              <select value={fmtStatus} onChange={(e) => setFmtStatus(e.target.value)} aria-label="Статус в формате" style={{ width: "auto" }}>
                <option value="f">разрешена в</option>
                <option value="banned">запрещена в</option>
                <option value="restricted">ограничена в</option>
              </select>
              <select id="a-fmt" value={fmt} onChange={(e) => setFmt(e.target.value)} style={{ width: "auto" }}>
                <option value="">—</option>
                {FORMATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </span>

            <label>Особое</label>
            <div className="colors row">
              <label><input type="checkbox" checked={gc} onChange={(e) => setGc(e.target.checked)} /> Game Changer</label>
              <label><input type="checkbox" checked={ru} onChange={(e) => setRu(e.target.checked)} /> есть русское название</label>
            </div>

            <label htmlFor="a-art">Художник</label>
            <input id="a-art" value={artist} onChange={(e) => setArtist(e.target.value)} />

            <label htmlFor="a-usd">Цена, $</label>
            <NumField id="a-usd" value={usd} set={setUsd} />
          </>
        ) : null}

        <label htmlFor="a-order">Сортировка</label>
        <select id="a-order" value={order} onChange={(e) => setOrder(e.target.value)} style={{ width: "auto" }}>
          {ORDER_LABELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>

        <span />
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>Запрос: <code>{query || "*"}</code></p>
          <div><button type="submit" className="primary">Найти карты</button></div>
        </div>
      </form>
    </>
  );
}

export default function AdvancedPage() {
  return <Suspense fallback={<h1>Расширенный поиск</h1>}><Advanced /></Suspense>;
}
