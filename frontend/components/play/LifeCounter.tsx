"use client";

import { useEffect, useRef, useState } from "react";
import { outcomeOf, scoreText } from "@/lib/play";

/** Счётчик жизней MTG: 2-6 игроков, яд, урон от командиров, счёт матча до двух побед.
 *  Состояние хранится на телефоне - случайно закрытая вкладка ничего не сбрасывает. */

type P = { name: string; life: number; poison: number; cmd: number[] };
type S = { start: number; players: P[]; games: [number, number, number]; log: string[] };
type Loss = { who: number; why: string };

const KEY = "dragon_life_v1";
const COLORS = ["#6b4fa8", "#2f6f8f", "#8a2a17", "#2f7a52", "#9a7a2a", "#5a5f73"];

const fresh = (n: number, start: number, names?: string[]): P[] =>
  Array.from({ length: n }, (_, i) => ({ name: names?.[i] || `Игрок ${i + 1}`, life: start, poison: 0, cmd: Array(n).fill(0) }));

function load(): S | null {
  try { const s = JSON.parse(window.localStorage.getItem(KEY) || "null"); return s?.players?.length ? s : null; } catch { return null; }
}

export default function LifeCounter({ me, opponent, onMatch }: {
  me?: string; opponent?: string;
  onMatch?: (score: [number, number, number]) => void;     // счёт матча изменился (для отправки судье)
}) {
  const [s, setS] = useState<S>({ start: 20, players: fresh(2, 20), games: [0, 0, 0], log: [] });
  const [loss, setLoss] = useState<Loss | null>(null);
  const [cmdOf, setCmdOf] = useState<number | null>(null);      // панель урона командиров для игрока
  const [full, setFull] = useState(false);
  const ready = useRef(false);

  useEffect(() => { const x = load(); if (x) setS(x); ready.current = true; }, []);
  useEffect(() => { if (ready.current) try { window.localStorage.setItem(KEY, JSON.stringify(s)); } catch {} }, [s]);
  // имена из турнира: я снизу, соперник сверху
  useEffect(() => {
    if (!me || !opponent) return;
    setS((x) => x.players.length !== 2 || (x.players[0].name === me && x.players[1].name === opponent) ? x
      : { ...x, players: [{ ...x.players[0], name: me }, { ...x.players[1], name: opponent }] });
  }, [me, opponent]);
  useEffect(() => { onMatch?.(s.games); }, [s.games, onMatch]);

  // экран не гаснет, пока открыт счётчик
  useEffect(() => {
    let lock: any = null;
    const take = async () => { try { lock = await (navigator as any).wakeLock?.request("screen"); } catch {} };
    take();
    const vis = () => { if (document.visibilityState === "visible") take(); };
    document.addEventListener("visibilitychange", vis);
    return () => { document.removeEventListener("visibilitychange", vis); try { lock?.release(); } catch {} };
  }, []);

  const duel = s.players.length === 2;
  const check = (p: P[], i: number) => {
    const x = p[i];
    const why = x.life <= 0 ? "жизни закончились" : x.poison >= 10 ? "10 жетонов яда"
      : x.cmd.some((d) => d >= 21) ? "21 урон от одного командира" : "";
    if (why) setLoss({ who: i, why });
  };
  const change = (i: number, f: (p: P) => P, note: string) => setS((x) => {
    const players = x.players.map((p, j) => (j === i ? f(p) : p));
    setTimeout(() => check(players, i), 0);
    return { ...x, players, log: [`${x.players[i].name}: ${note}`, ...x.log].slice(0, 60) };
  });
  const life = (i: number, d: number) => change(i, (p) => ({ ...p, life: p.life + d }), `${d > 0 ? "+" : ""}${d} → ${s.players[i].life + d}`);
  const poison = (i: number, d: number) => change(i, (p) => ({ ...p, poison: Math.max(0, p.poison + d) }), `яд ${d > 0 ? "+" : ""}${d}`);
  const cmd = (i: number, from: number, d: number) => change(i, (p) => {
    const c = [...p.cmd]; c[from] = Math.max(0, c[from] + d);
    return { ...p, cmd: c, life: p.life - d };
  }, `урон от командира ${s.players[from].name} ${d > 0 ? "+" : ""}${d}`);

  const newGame = (games = s.games) => setS((x) => ({ ...x, games, players: fresh(x.players.length, x.start, x.players.map((p) => p.name)),
    log: [`— новая партия (${scoreText(games)}) —`, ...x.log].slice(0, 60) }));
  const award = (loser: number | null) => {           // null - ничья в партии
    const g: [number, number, number] = [...s.games];
    if (loser === null) g[2]++; else g[loser === 0 ? 1 : 0]++;
    setLoss(null);
    newGame(g);
  };
  const setup = (n: number, start: number) => {
    setS({ start, players: fresh(n, start, n === 2 && me && opponent ? [me, opponent] : undefined), games: [0, 0, 0], log: [] });
    setLoss(null);
  };
  const matchOver = duel && (s.games[0] >= 2 || s.games[1] >= 2);

  return (
    <div className={`life${full ? " life-full" : ""}`}>
      <div className="life-bar row">
        <select aria-label="Игроков" value={s.players.length} onChange={(e) => setup(+e.target.value, s.start)}>
          {[2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} игрока</option>)}
        </select>
        <select aria-label="Стартовые жизни" value={s.start} onChange={(e) => setup(s.players.length, +e.target.value)}>
          {[20, 25, 30, 40].map((n) => <option key={n} value={n}>{n} жизней{n === 40 ? " (Commander)" : ""}</option>)}
        </select>
        <button type="button" className="link-btn" onClick={() => newGame()}>Новая партия</button>
        <button type="button" className="link-btn" onClick={() => setup(s.players.length, s.start)}>Сбросить матч</button>
        <button type="button" className="link-btn" onClick={() => setFull((f) => !f)}>{full ? "Свернуть" : "Во весь экран"}</button>
      </div>

      {duel ? (
        <p className="life-score" aria-live="polite">
          Матч: <b>{s.players[0].name} {s.games[0]} — {s.games[1]} {s.players[1].name}</b>{s.games[2] ? ` · ничьих ${s.games[2]}` : ""}
          {matchOver ? <span className="badge" style={{ marginLeft: 8 }}>{outcomeOf(s.games) === "win" ? `победил ${s.players[0].name}` : `победил ${s.players[1].name}`} {scoreText(s.games)}</span> : null}
        </p>
      ) : null}

      <div className={`life-grid n${s.players.length}`}>
        {s.players.map((p, i) => (
          <section key={i} className={`life-p${duel && i === 1 ? " flip" : ""}`} style={{ background: COLORS[i] }} aria-label={p.name}>
            <div className="life-name">{p.name}</div>
            <button type="button" className="life-half minus" aria-label={`${p.name}: минус 1`} onClick={() => life(i, -1)} />
            <button type="button" className="life-half plus" aria-label={`${p.name}: плюс 1`} onClick={() => life(i, 1)} />
            <div className="life-num" aria-live="polite">{p.life}</div>
            <div className="life-tools">
              <button type="button" onClick={() => life(i, -5)}>−5</button>
              <button type="button" onClick={() => poison(i, 1)} onContextMenu={(e) => { e.preventDefault(); poison(i, -1); }}
                title="Яд (долгое нажатие — снять)">☠ {p.poison}</button>
              {s.start >= 30 || s.players.length > 2 ? (
                <button type="button" onClick={() => setCmdOf(cmdOf === i ? null : i)}>⚔ {Math.max(...p.cmd)}</button>
              ) : null}
              <button type="button" onClick={() => life(i, 5)}>+5</button>
            </div>
            {cmdOf === i ? (
              <div className="life-cmd">
                <b>Урон от командиров</b>
                {s.players.map((q, j) => j === i ? null : (
                  <div key={j} className="row">
                    <span>{q.name}: {p.cmd[j]}</span>
                    <button type="button" onClick={() => cmd(i, j, -1)}>−</button>
                    <button type="button" onClick={() => cmd(i, j, 1)}>+</button>
                  </div>
                ))}
                {p.poison ? <button type="button" className="link-btn" onClick={() => poison(i, -1)}>снять 1 яд</button> : null}
              </div>
            ) : null}
          </section>
        ))}
      </div>

      {loss ? (
        <div className="life-modal" role="dialog" aria-label="Конец партии">
          <p><b>{s.players[loss.who].name}</b> проигрывает партию: {loss.why}.</p>
          <div className="row">
            {duel ? <button type="button" className="primary" onClick={() => award(loss.who)}>Засчитать партию</button>
              : <button type="button" className="primary" onClick={() => setLoss(null)}>Понятно</button>}
            <button type="button" className="link-btn" onClick={() => setLoss(null)}>Продолжить игру</button>
          </div>
        </div>
      ) : null}

      {duel ? (
        <div className="row life-extra">
          <button type="button" className="link-btn" onClick={() => award(null)}>Партия: ничья</button>
          <button type="button" className="link-btn" onClick={() => setS((x) => ({ ...x, games: [0, 0, 0] }))}>Обнулить счёт матча</button>
        </div>
      ) : null}
      {s.log.length ? (
        <details className="life-log"><summary>История ({s.log.length})</summary>
          <ol>{s.log.map((l, i) => <li key={i}>{l}</li>)}</ol>
        </details>
      ) : null}
    </div>
  );
}
