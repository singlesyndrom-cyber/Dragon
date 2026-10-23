import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "@/components/Markdown";
import RatingAdmin from "@/components/RatingAdmin";
import Standings, { Delta } from "@/components/Standings";
import TournamentActions from "@/components/TournamentActions";
import { sget } from "@/lib/api";
import { dateTime, FORMATS, GAMES, signed, T_STATUS } from "@/lib/format";
import { DISCIPLINE_NAME, TIER_NAME } from "@/lib/rating";

const RESULT: Record<string, string> = { p1: "победа первого", p2: "победа второго", draw: "ничья" };

export default async function TournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await sget<any>(`/tournaments/${id}`);
  if (!t) notFound();
  const isEdh = t.format === "edh";
  const rt = t.status === "finished" ? await sget<any>(`/ratings/tournaments/${id}`) : null;
  const ratingBlock = rt ? (
    <section className="section">
      <h2>Рейтинг силы · {DISCIPLINE_NAME[rt.discipline] || rt.discipline}</h2>
      {rt.changes.length ? (
        <div className="table-wrap">
          <table className="rating-table">
            <thead><tr><th>Игрок</th><th className="r">Было</th><th className="r">Стало</th><th className="r">Изменение</th><th className="r">Партий</th></tr></thead>
            <tbody>
              {rt.changes.map((c: any) => (
                <tr key={c.user_id}>
                  <td>{c.player_no ? <Link href={`/players/${c.player_no}`}>{c.nickname}</Link> : c.nickname}</td>
                  <td className="r num">{c.before}</td><td className="r num">{c.after}</td>
                  <td className={`r num ${c.delta > 0 ? "win" : c.delta < 0 ? "loss" : "muted"}`}>{c.delta > 0 ? "+" : ""}{c.delta}</td>
                  <td className="r num">{c.games}{c.ignored ? <span className="muted small" title="Не засчитаны защитой от накрутки: та же пара слишком часто за 30 дней"> (+{c.ignored} не засч.)</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Турнир не повлиял на рейтинг: {rt.reason}.</p>}
      <p className="muted small"><Link href={`/ratings?discipline=${rt.discipline}`}>Таблица рейтинга →</Link></p>
    </section>
  ) : null;

  let body: React.ReactNode = null;
  if (isEdh) {
    const [tables, results] = await Promise.all([
      t.round ? sget<any[]>(`/edh/${id}/tables`) : Promise.resolve([]),
      sget<any[]>(`/edh/${id}/results`),
    ]);
    body = (
      <>
        {tables?.length ? (
          <>
            <h2>Столы, тур {t.round}</h2>
            {tables.map((tb) => (
              <div key={tb.table_id} className="panel">
                <div className="row">
                  <h3 style={{ margin: 0 }}>Стол {tb.table}</h3>
                  <span className="badge">брекет {tb.bracket}</span>
                  <span className={tb.status === "playing" ? "badge live" : "badge"}>
                    {tb.status === "playing" ? `осталось ${Math.ceil(tb.seconds_left / 60)} мин`
                      : tb.outcome === "win" ? "есть победитель" : "без победителя"}
                  </span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Игрок</th><th className="r">Банк до</th><th className="r">Изменение</th></tr></thead>
                    <tbody>
                      {tb.seats.map((s: any) => (
                        <tr key={s.user_id} className={tb.outcome === "win" && s.delta > 0 ? "winner" : undefined}>
                          <td>{s.nickname}{tb.outcome === "win" && s.delta > 0 ? ", победитель" : ""}</td>
                          <td className="r">{Math.round(s.bank_before)}</td>
                          <td className="r"><Delta v={s.delta} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </>
        ) : null}
        <h2>Итог ивента</h2>
        <Standings head={["Партий", "Изменение банка", "Банк"]} empty="Результатов пока нет."
          rows={(results || []).map((r, i, all) => ({
            // одинаковый итог — одно место: 1, 2, 2, 4…
            rank: all.findIndex((x) => Math.round(x.net * 10) === Math.round(r.net * 10)) + 1, name: r.nickname,
            prize: r.net > 0 && i < 3,   // в EDH призёры — только те, кто остался в плюсе
            cells: [r.games, signed(r.net), r.bank !== null ? Math.round(r.bank).toLocaleString("ru-RU") : "—"],
          }))} />
      </>
    );
  } else {
    const [standings, pairings] = await Promise.all([
      t.round ? sget<any[]>(`/tournaments/${id}/standings`) : Promise.resolve([]),
      t.round ? sget<any[]>(`/tournaments/${id}/round/${t.round}`) : Promise.resolve([]),
    ]);
    const pairsBlock = (
      <>
        {pairings?.length ? (
          <>
            <h2>{t.status === "finished" ? `Пары последнего тура (${t.round})` : `Пары, тур ${t.round}`}</h2>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Стол</th><th>Игрок 1</th><th>Игрок 2</th><th>Результат</th></tr></thead>
                <tbody>
                  {pairings.map((m) => (
                    <tr key={m.match_id}>
                      <td className="num">{m.table}</td>
                      <td>{m.p1}</td>
                      <td>{m.p2 ?? <span className="muted">пропуск тура (bye)</span>}</td>
                      <td className="muted">{m.p2 ? (m.result ? RESULT[m.result] : "играют") : "победа"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </>
    );
    const tableBlock = (
      <>
        <h2>Таблица</h2>
        <Standings head={["Очки", "OWP", "Buchholz"]} empty="Таблица появится после первого тура."
          rows={(standings || []).map((r) => ({
            rank: r.rank, name: r.player, cells: [r.points, (r.owp * 100).toFixed(1) + "%", r.buchholz],
          }))} />
      </>
    );
    // идёт игра — сначала пары текущего тура; турнир завершён — сначала итоговая таблица
    body = t.status === "finished" ? <>{tableBlock}{pairsBlock}</> : <>{pairsBlock}{tableBlock}</>;
  }

  return (
    <>
      <h1>{t.name}</h1>
      <div className="split">
        <div>
          <dl className="facts">
            <dt>Клуб</dt><dd><Link href={`/clubs/${t.club_slug}`}>{t.club}</Link></dd>
            <dt>Формат</dt><dd>{FORMATS[t.format] || t.format}, {GAMES[t.game] || t.game}</dd>
            {t.tier && t.tier !== "club" ? (<><dt>Уровень</dt><dd>{TIER_NAME[t.tier] || t.tier}{["open", "regional", "pro"].includes(t.tier)
              ? <span className="muted small"> — игроки других городов записываются со своим номером, без вступления в клуб</span> : null}</dd></>) : null}
            <dt>Начало</dt><dd>{dateTime(t.starts_at)}</dd>
            <dt>Статус</dt><dd>{T_STATUS[t.status]}{t.round ? `, тур ${t.round}${t.rounds_total ? ` из ${t.rounds_total}` : ""}` : ""}</dd>
            <dt>Участники</dt><dd>{t.players}{t.max_players ? ` из ${t.max_players}` : ""}</dd>
            {t.judge ? (<><dt>Судья</dt><dd>{t.judge.player_no ? <Link href={`/players/${t.judge.player_no}`}>{t.judge.nickname}</Link> : t.judge.nickname}</dd></>) : null}
            {t.league ? (<><dt>Сезон лиги</dt><dd><Link href={`/leagues/${t.league.id}`}>{t.league.name}</Link></dd></>) : null}
          </dl>
          {t.description ? <div className="section"><Markdown text={t.description} /></div> : null}
          {isEdh ? (
            <p className="muted small" style={{ marginTop: 16 }}>
              Партия длится 70 минут. Победитель забирает по 7% банка у каждого соперника; если победителя нет,
              каждый теряет 7% своего банка. Рассадка случайная внутри брекетов.
            </p>
          ) : null}
          {body}
          {ratingBlock}
          {t.status === "finished" ? <RatingAdmin tid={t.id} rated={t.rated !== false} tier={t.tier || "club"} /> : null}
        </div>
        <aside>
          <TournamentActions t={t} />
          <h3 style={{ marginTop: 24 }}>Участники</h3>
          {t.participants.length ? (
            <ul className="news-list">
              {t.participants.map((p: any) => (
                <li key={p.user_id} style={{ padding: "8px 0" }}>
                  {p.nickname}
                  {isEdh ? <span className="muted small">, брекет {p.bracket}</span> : null}
                  {p.guest ? <span className="badge" style={{ marginLeft: 8 }}>гость</span> : null}
                  {p.dropped ? <span className="badge" style={{ marginLeft: 8 }}>выбыл</span> : null}
                </li>
              ))}
            </ul>
          ) : <p className="muted">Пока никто не записался.</p>}
        </aside>
      </div>
    </>
  );
}
