"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { viaSite } from "@/lib/img";
import { BK_CREDIT } from "@/lib/berserk";
import { canMulligan, canTake, EMPTY_SQUAD, type SquadCard, type SquadState, squadSummary, toSquadCard } from "@/lib/play";

/** «Берсерк»: набор отряда за кристаллы по Расширенным правилам 6.1-1 (п. 402-403).
 *  Колода берётся из личного кабинета и сохраняется на телефоне - набор работает и без интернета. */

const KEY = "dragon_squad_v1";
const DECKS = "dragon_bk_decks_v1";

type Pool = { deckId: number | null; name: string; cards: { card: SquadCard; qty: number }[] };
type Saved = { state: SquadState; pool: Pool | null; rolls: string[] };

function read<T>(k: string): T | null {
  try { return JSON.parse(window.localStorage.getItem(k) || "null"); } catch { return null; }
}
function write(k: string, v: unknown) {
  try { window.localStorage.setItem(k, JSON.stringify(v)); } catch {}
}

export default function SquadBuilder() {
  const { me } = useAuth();
  const [st, setSt] = useState<SquadState>(EMPTY_SQUAD);
  const [pool, setPool] = useState<Pool | null>(null);
  const [rolls, setRolls] = useState<string[]>([]);
  const [decks, setDecks] = useState<{ id: number; name: string }[]>([]);
  const [offline, setOffline] = useState<Record<number, Pool>>({});
  const [msg, setMsg] = useState("");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<SquadCard[]>([]);
  const ready = useRef(false);

  useEffect(() => {
    const s = read<Saved>(KEY);
    if (s) { setSt({ ...EMPTY_SQUAD, ...s.state }); setPool(s.pool); setRolls(s.rolls || []); }
    setOffline(read<Record<number, Pool>>(DECKS) || {});
    ready.current = true;
  }, []);
  useEffect(() => { if (ready.current) write(KEY, { state: st, pool, rolls }); }, [st, pool, rolls]);
  useEffect(() => {
    if (!me) return;
    api<any[]>("/decks/mine").then((x) => setDecks(x.filter((d) => d.game === "berserk"))).catch(() => {});
  }, [me]);

  const pickDeck = async (id: number) => {
    setMsg("");
    try {
      const d = await api<any>(`/decks/${id}`);
      const cards = (d.cards as any[]).filter((c) => c.section !== "side" && c.card)
        .map((c, i) => ({ card: toSquadCard(c.card, `${id}-${i}`), qty: c.qty }))
        .filter((x): x is { card: SquadCard; qty: number } => !!x.card)
        .sort((a, b) => a.card.cost - b.card.cost || a.card.name.localeCompare(b.card.name, "ru"));
      const p = { deckId: id, name: d.name, cards };
      setPool(p);
      const o = { ...offline, [id]: p };
      setOffline(o); write(DECKS, o);
    } catch {
      if (offline[id]) { setPool(offline[id]); setMsg("Нет связи — взята сохранённая на телефоне копия колоды."); }
      else setMsg("Нет связи, а колода ещё не сохранена на телефоне. Откройте её один раз с интернетом.");
    }
  };

  useEffect(() => {
    if (q.trim().length < 2) { setFound([]); return; }
    const t = window.setTimeout(() => {
      api<any[]>(`/cards?game=berserk&limit=12&q=${encodeURIComponent(q.trim())}`)
        .then((x) => setFound(x.map((c) => toSquadCard(c, `s-${c.id}`)).filter((c): c is SquadCard => !!c))).catch(() => setFound([]));
    }, 300);
    return () => window.clearTimeout(t);
  }, [q]);

  const sum = squadSummary(st);
  const used = (key: string) => st.squad.filter((c) => c.key === key || c.key.startsWith(key + "#")).length;
  const take = (c: SquadCard) => {
    const p = canTake(st, c);
    if (p.length) { setMsg(`Нельзя взять «${c.name}»: ${p.join("; ")}.`); return; }
    setMsg("");
    setSt((s) => ({ ...s, squad: [...s.squad, { ...c, key: `${c.key}#${Date.now()}` }] }));
  };
  const drop = (i: number) => setSt((s) => ({ ...s, squad: s.squad.filter((_, j) => j !== i) }));
  const toggleFly = (i: number) => setSt((s) => ({ ...s, squad: s.squad.map((c, j) => (j === i ? { ...c, flying: !c.flying } : c)) }));
  const roll = () => setRolls((r) => [`${1 + Math.floor(Math.random() * 6)}`, ...r].slice(0, 12));
  const restart = () => { setSt(EMPTY_SQUAD); setRolls([]); setMsg(""); };

  return (
    <div className="squad">
      <section className="squad-crystals" aria-live="polite" aria-label="Кристаллы">
        <div className="crys gold"><span>Золото</span><b>{sum.goldLeft}</b><small>из {sum.gold0}</small></div>
        <div className="crys silver"><span>Серебро</span><b>{sum.silverLeft}</b><small>из {sum.silver0}</small></div>
        <div className="crys"><span>Карт</span><b>{st.squad.length}</b><small>клеток {st.cells}</small></div>
        <div className="crys"><span>Летающие</span><b>{sum.flyCost}</b><small>из 15</small></div>
      </section>
      {sum.problems.map((p) => <p key={p} className="err">{p}</p>)}
      {sum.warnings.map((p) => <p key={p} className="muted small">{p}</p>)}
      {sum.elements.length ? <p className="muted small">Стихии: {sum.elements.join(", ")}{sum.penalty ? ` — штраф ${sum.penalty} зол.` : ""}</p> : null}
      {msg ? <p className="err" role="alert">{msg}</p> : null}

      <div className="row squad-setup">
        <label className="check"><input type="checkbox" checked={st.second} onChange={(e) => setSt({ ...st, second: e.target.checked })} /><span>Хожу вторым (+1 зол., +1 сер.)</span></label>
        <button type="button" disabled={!canMulligan(st)} onClick={() => setSt({ ...st, mulligans: st.mulligans + 1 })}
          title={canMulligan(st) ? "" : "Без золота пересдача — поражение (п. 402.4)"}>Пересдача −1 зол. ({st.mulligans})</button>
        {st.mulligans ? <button type="button" className="link-btn" onClick={() => setSt({ ...st, mulligans: st.mulligans - 1 })}>отменить пересдачу</button> : null}
        <button type="button" onClick={roll}>🎲 Кубик{rolls[0] ? `: ${rolls[0]}` : ""}</button>
      </div>
      {rolls.length > 1 ? <p className="muted small">Броски: {rolls.join(", ")}</p> : null}
      <details className="squad-more"><summary>Поправки от особенностей карт и клетки</summary>
        <div className="row">
          <span>Золото {st.bonusGold >= 0 ? "+" : ""}{st.bonusGold}</span>
          <button type="button" onClick={() => setSt({ ...st, bonusGold: st.bonusGold - 1 })}>−</button>
          <button type="button" onClick={() => setSt({ ...st, bonusGold: st.bonusGold + 1 })}>+</button>
          <span>Серебро {st.bonusSilver >= 0 ? "+" : ""}{st.bonusSilver}</span>
          <button type="button" onClick={() => setSt({ ...st, bonusSilver: st.bonusSilver - 1 })}>−</button>
          <button type="button" onClick={() => setSt({ ...st, bonusSilver: st.bonusSilver + 1 })}>+</button>
          <span>Клеток {st.cells}</span>
          <button type="button" onClick={() => setSt({ ...st, cells: Math.max(1, st.cells - 1) })}>−</button>
          <button type="button" onClick={() => setSt({ ...st, cells: st.cells + 1 })}>+</button>
        </div>
        <p className="muted small">Например, особенность «при наборе отряда» дала 2 золотых — добавьте их здесь.</p>
      </details>

      <h3>Отряд</h3>
      {st.squad.length ? (
        <ul className="squad-list">
          {st.squad.map((c, i) => (
            <li key={c.key}>
              <span className={`cost${c.elite ? " elite" : ""}`}>{c.cost}</span>
              <span className="nm">{c.name}{c.unique ? " ◆" : ""}</span>
              {c.creature ? <button type="button" className={`fly${c.flying ? " on" : ""}`} aria-pressed={c.flying} onClick={() => toggleFly(i)}
                title="Летающее существо">🪽</button> : null}
              <button type="button" className="link-btn" aria-label={`Убрать ${c.name}`} onClick={() => drop(i)}>✕</button>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Нажимайте на карты раздачи ниже — они попадут в отряд, а кристаллы спишутся сами.</p>}
      <div className="row">
        {st.squad.length ? <button type="button" onClick={() => setSt({ ...st, squad: [] })}>Отменить набор (п. 403.2.4)</button> : null}
        <button type="button" className="link-btn" onClick={restart}>Новая партия</button>
      </div>

      <h3>Карты</h3>
      <div className="row">
        {me && decks.length ? (
          <select aria-label="Колода" value={pool?.deckId ?? ""} onChange={(e) => e.target.value && pickDeck(+e.target.value)}>
            <option value="">Выберите колоду…</option>
            {decks.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        ) : Object.keys(offline).length ? (
          <select aria-label="Сохранённая колода" value={pool?.deckId ?? ""} onChange={(e) => e.target.value && setPool(offline[+e.target.value])}>
            <option value="">Сохранённые колоды…</option>
            {Object.entries(offline).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}
          </select>
        ) : <span className="muted small">{me ? "Колод «Берсерка» в личном кабинете пока нет." : "Войдите, чтобы взять колоду из личного кабинета."}</span>}
        <input type="search" placeholder="Найти карту по названию" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Поиск карты" />
      </div>
      {found.length ? <CardGrid cards={found.map((c) => ({ card: c, qty: 99 }))} used={used} take={take} st={st} /> : null}
      {pool ? <CardGrid cards={pool.cards} used={used} take={take} st={st} /> : null}
      <p className="muted small">{BK_CREDIT} Летающие отмечены по базе карт; если ошиблись — нажмите 🪽 у карты в отряде.</p>
    </div>
  );
}

function CardGrid({ cards, used, take, st }: { cards: { card: SquadCard; qty: number }[]; used: (k: string) => number;
  take: (c: SquadCard) => void; st: SquadState }) {
  return (
    <ul className="squad-cards">
      {cards.map(({ card, qty }) => {
        const left = qty - used(card.key);
        const bad = left > 0 && canTake(st, card).length > 0;
        return (
          <li key={card.key}>
            <button type="button" disabled={left <= 0} className={bad ? "bad" : undefined} onClick={() => take({ ...card })}
              aria-label={`Взять ${card.name}, стоимость ${card.cost}${card.elite ? ", элитная" : ""}`}>
              {card.image ? <img src={viaSite(card.image) || ""} alt="" loading="lazy" /> : <span className="ph">{card.name}</span>}
              <span className={`cost${card.elite ? " elite" : ""}`}>{card.cost}</span>
              {qty < 99 ? <span className="qty">×{left}</span> : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
