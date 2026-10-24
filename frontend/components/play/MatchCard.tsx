"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { rememberReturn } from "@/lib/afterLogin";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { type CurrentMatch, type Outcome, OUTCOME_RU } from "@/lib/play";

const GAME_RU: Record<string, string> = { mtg: "Magic", berserk: "Берсерк", response: "Респонс" };
const SCORES: Record<Outcome, string[]> = { win: ["2-0", "2-1", "1-0"], loss: ["0-2", "1-2", "0-1"], draw: ["1-1", "1-1-1", "0-0-3", "0-0"] };

/** Текущий матч игрока в идущем турнире: соперник, стол, тур и отправка результата судье. */
export default function MatchCard({ suggest, onMatch }: {
  suggest?: { outcome: Outcome; score: string } | null;     // подсказка из счётчика жизней
  onMatch?: (m: CurrentMatch | null) => void;
}) {
  const { me, ready } = useAuth();
  const [items, setItems] = useState<CurrentMatch[] | null>(null);
  const load = useCallback(() => {
    if (!me) return;
    api<CurrentMatch[]>("/play/current").then((x) => { setItems(x); onMatch?.(x[0] ?? null); }).catch(() => {});
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
  return <>{items.map((m) => <One key={m.match_id} m={m} suggest={suggest} reload={load} />)}</>;
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
