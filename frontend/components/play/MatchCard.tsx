"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { rememberReturn } from "@/lib/afterLogin";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { type Current, type CurrentEdh, type CurrentMatch, type Outcome, OUTCOME_RU } from "@/lib/play";

const GAME_RU: Record<string, string> = { mtg: "Magic", berserk: "Берсерк", response: "Респонс" };
const SCORES: Record<Outcome, string[]> = { win: ["2-0", "2-1", "1-0"], loss: ["0-2", "1-2", "0-1"], draw: ["1-1", "1-1-1", "0-0-3", "0-0"] };

/** Текущий матч игрока в идущем турнире: соперник, стол, тур и отправка результата судье. */
export default function MatchCard({ suggest, edhWinner, onMatch }: {
  suggest?: { outcome: Outcome; score: string } | null;     // подсказка из счётчика жизней (дуэль)
  edhWinner?: string | null;                                // EDH: кто остался последним в счётчике
  onMatch?: (m: Current | null) => void;
}) {
  const { me, ready } = useAuth();
  const [items, setItems] = useState<Current[] | null>(null);
  const load = useCallback(() => {
    if (!me) return;
    api<Current[]>("/play/current").then((x) => { setItems(x); onMatch?.(x[0] ?? null); }).catch(() => {});
  }, [me, onMatch]);
  useEffect(() => {
    load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 15000);
    return () => window.clearInterval(t);
  }, [load]);

  if (!ready) return null;
  if (!me) {
    return (
      <section className="panel play-match">
        <p style={{ margin: 0 }}><Link href="/login" onClick={() => rememberReturn("/play")}>Войдите</Link>, чтобы видеть соперника в турнире и отправлять результат судье.
          Счётчики работают и без входа.</p>
      </section>
    );
  }
  if (!items) return null;
  if (!items.length) {
    return <p className="muted small play-match">Сейчас вы не играете в идущем турнире. Когда начнётся тур, здесь появится ваш соперник.</p>;
  }
  return <>{items.map((m) => m.kind === "edh"
    ? <Edh key={`e${m.table_id}`} m={m} suggest={edhWinner} reload={load} />
    : <One key={m.match_id} m={m} suggest={suggest} reload={load} />)}</>;
}

function One({ m, suggest, reload }: { m: CurrentMatch; suggest?: { outcome: Outcome; score: string } | null; reload: () => void }) {
  const { busy, error, done, run } = useAction();
  const [outcome, setOutcome] = useState<Outcome | null>(m.my_report?.outcome ?? null);
  const [score, setScore] = useState<string>(m.my_report?.score ?? "");
  useEffect(() => {
    if (suggest && !m.my_report && m.tournament.game === "mtg") { setOutcome(suggest.outcome); setScore(suggest.score); }
  }, [suggest, m.my_report, m.tournament.game]);

  const t = m.tournament;
  const send = (source: "manual" | "life") => run(() => api(`/play/matches/${m.match_id}/report`,
    { body: { outcome, score: score || null, source } }), "Отправлено судье").then(reload);
  const mine = m.my_report, theirs = m.opp_report;
  const agree = mine && theirs && mine.outcome === ({ win: "loss", loss: "win", draw: "draw" } as const)[theirs.outcome];

  return (
    <section className="panel play-match" aria-label="Мой матч">
      <div className="muted small">{GAME_RU[t.game] || t.game} · {t.club} · <Link href={`/tournaments/${t.id}`}>{t.name}</Link></div>
      <h2 style={{ margin: "4px 0" }}>Тур {t.round}{t.rounds_total ? ` из ${t.rounds_total}` : ""} · стол {m.table}</h2>
      {m.bye ? <p>У вас <b>bye</b> — в этом туре вы без соперника, победа засчитана.</p> : (
        <>
          <p className="play-opp">Соперник: <b>{m.opponent?.player_no ? <Link href={`/players/${m.opponent.player_no}`}>{m.opponent?.nickname}</Link> : m.opponent?.nickname}</b>
            {m.opponent?.player_no ? <span className="muted small"> № {m.opponent.player_no}</span> : null}
            {m.opponent?.rating ? <span className="muted small"> · рейтинг {m.opponent.rating.rating}</span> : null}</p>
          {m.result ? (
            <p className="ok">Судья внёс результат: <b>{OUTCOME_RU[m.result]}</b>.</p>
          ) : (
            <>
              <div className="row" role="group" aria-label="Итог матча">
                {(["win", "draw", "loss"] as Outcome[]).map((o) => (
                  <button key={o} type="button" className={outcome === o ? "primary" : ""} aria-pressed={outcome === o}
                    onClick={() => { setOutcome(o); setScore(SCORES[o][0]); }}>{o === "win" ? "Я победил" : o === "loss" ? "Я проиграл" : "Ничья"}</button>
                ))}
                {outcome ? (
                  <select aria-label="Счёт по партиям" value={score} onChange={(e) => setScore(e.target.value)}>
                    {[...new Set([score, ...SCORES[outcome]].filter(Boolean))].map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                ) : null}
                <button type="button" className="primary" disabled={!outcome || busy}
                  onClick={() => send(suggest && suggest.outcome === outcome && suggest.score === score ? "life" : "manual")}>
                  {mine ? "Исправить" : "Отправить судье"}
                </button>
              </div>
              {suggest && t.game === "mtg" && !mine ? <p className="muted small">Счёт подставлен из счётчика жизней — проверьте перед отправкой.</p> : null}
              <p className="small" aria-live="polite">
                {mine ? <>Вы отправили: <b>{OUTCOME_RU[mine.outcome]}{mine.score ? ` ${mine.score}` : ""}</b>. </> : null}
                {theirs ? <>Соперник: <b>{OUTCOME_RU[theirs.outcome]}{theirs.score ? ` ${theirs.score}` : ""}</b>. </> : mine ? "Ждём подтверждения соперника. " : null}
                {mine && theirs ? (agree ? <span className="ok">Результаты совпали — судья внесёт их.</span>
                  : <span className="err">Результаты не совпали — подойдите к судье.</span>) : null}
              </p>
            </>
          )}
        </>
      )}
      <Status error={error} done={done} />
    </section>
  );
}

function Timer({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => { setLeft(seconds); const t = window.setInterval(() => setLeft((x) => Math.max(0, x - 1)), 1000); return () => window.clearInterval(t); }, [seconds]);
  const m = Math.floor(left / 60), s = left % 60;
  return <b className={left < 600 ? "err" : undefined} style={{ margin: 0 }}>{left ? `${m}:${String(s).padStart(2, "0")}` : "время вышло"}</b>;
}

/** EDH: стол на 3-5 игроков, таймер, кто победил - отправляет любой игрок за столом. */
function Edh({ m, suggest, reload }: { m: CurrentEdh; suggest?: string | null; reload: () => void }) {
  const { busy, error, done, run } = useAction();
  const [pick, setPick] = useState<string>(m.my_report ? (m.my_report.outcome === "draw" ? "draw" : String(m.my_report.winner_id)) : "");
  useEffect(() => {
    if (!suggest || m.my_report) return;
    const s = m.seats.find((x) => x.nickname === suggest);
    if (s) setPick(String(s.user_id));
  }, [suggest, m.my_report, m.seats]);
  const t = m.tournament;
  const send = () => run(() => api(`/play/edh/${m.table_id}/report`, {
    body: pick === "draw" ? { outcome: "draw" } : { outcome: "win", winner_id: +pick,
      source: suggest && m.seats.find((x) => String(x.user_id) === pick)?.nickname === suggest ? "life" : "manual" },
  }), "Отправлено судье").then(reload);
  const says = (r: { outcome: string; winner: string | null }) => r.outcome === "draw" ? "ничья" : `победил ${r.winner}`;
  const all = [...(m.my_report ? [m.my_report] : []), ...m.reports];
  const same = all.length > 1 && new Set(all.map((r) => r.outcome === "draw" ? "d" : r.winner_id)).size === 1;

  return (
    <section className="panel play-match" aria-label="Мой стол EDH">
      <div className="muted small">{GAME_RU[t.game] || t.game} · {t.club} · <Link href={`/tournaments/${t.id}`}>{t.name}</Link></div>
      <h2 style={{ margin: "4px 0" }}>Тур {t.round} · стол {m.table} <span className="muted small">брекет {m.bracket}</span></h2>
      <p style={{ margin: "4px 0 10px" }}>{m.status === "playing" ? <>До конца партии: <Timer seconds={m.seconds_left} /></> : null}</p>
      <ul className="edh-seats">
        {m.seats.map((s) => (
          <li key={s.user_id} className={s.me ? "me" : undefined}>
            {s.player_no ? <Link href={`/players/${s.player_no}`}>{s.nickname}</Link> : s.nickname}{s.me ? " (вы)" : ""}
          </li>
        ))}
      </ul>
      {m.status === "finished" ? (
        <p className="ok">Стол закрыт: <b>{m.outcome === "win" ? `победил ${m.winner}` : m.outcome === "draw" ? "ничья" : "время вышло — проиграли все"}</b>.</p>
      ) : (
        <>
          <div className="row">
            <select aria-label="Итог стола" value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="" disabled>Кто победил?</option>
              {m.seats.map((s) => <option key={s.user_id} value={s.user_id}>Победил: {s.nickname}{s.me ? " (я)" : ""}</option>)}
              <option value="draw">Ничья</option>
            </select>
            <button type="button" className="primary" disabled={!pick || busy} onClick={send}>{m.my_report ? "Исправить" : "Отправить судье"}</button>
          </div>
          {suggest && !m.my_report ? <p className="muted small">Победитель подставлен из счётчика жизней — проверьте перед отправкой.</p> : null}
          <p className="small" aria-live="polite">
            {m.my_report ? <>Вы отправили: <b>{says(m.my_report)}</b>. </> : null}
            {m.reports.map((r) => <span key={r.nickname}>{r.nickname}: <b>{says(r)}</b>. </span>)}
            {all.length > 1 ? (same ? <span className="ok">Отчёты совпали — судья закроет стол.</span>
              : <span className="err">Отчёты расходятся — позовите судью.</span>) : m.my_report ? "Ждём, что скажут остальные. " : null}
          </p>
          <p className="muted small">Победу, о которой сообщили до конца таймера, судья сможет засчитать и после него.</p>
        </>
      )}
      <Status error={error} done={done} />
    </section>
  );
}
