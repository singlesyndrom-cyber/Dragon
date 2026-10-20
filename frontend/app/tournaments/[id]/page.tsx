import Link from "next/link";
import { notFound } from "next/navigation";
import Standings, { Delta } from "@/components/Standings";
import TournamentActions from "@/components/TournamentActions";
import { sget } from "@/lib/api";
import { dateTime, FORMATS, GAMES, signed, T_STATUS } from "@/lib/format";

const RESULT: Record<string, string> = { p1: "победа первого", p2: "победа второго", draw: "ничья" };

export default async function TournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await sget<any>(`/tournaments/${id}`);
  if (!t) notFound();
  const isEdh = t.format === "edh";

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
                        <tr key={s.user_id}>
                          <td>{s.nickname}</td>
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
          rows={(results || []).map((r, i) => ({
            rank: i + 1, name: r.nickname,
            cells: [r.games, signed(r.net), r.bank !== null ? Math.round(r.bank).toLocaleString("ru-RU") : "—"],
          }))} />
      </>
    );
  } else {
    const [standings, pairings] = await Promise.all([
      t.round ? sget<any[]>(`/tournaments/${id}/standings`) : Promise.resolve([]),
      t.round ? sget<any[]>(`/tournaments/${id}/round/${t.round}`) : Promise.resolve([]),
    ]);
    body = (
      <>
        {pairings?.length ? (
          <>
            <h2>Пары, тур {t.round}</h2>
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
        <h2>Таблица</h2>
        <Standings head={["Очки", "OWP", "Buchholz"]} empty="Таблица появится после первого тура."
          rows={(standings || []).map((r) => ({
            rank: r.rank, name: r.player, cells: [r.points, (r.owp * 100).toFixed(1) + "%", r.buchholz],
          }))} />
      </>
    );
  }

  return (
    <>
      <h1>{t.name}</h1>
      <div className="split">
        <div>
          <dl className="facts">
            <dt>Клуб</dt><dd><Link href={`/clubs/${t.club_slug}`}>{t.club}</Link></dd>
            <dt>Формат</dt><dd>{FORMATS[t.format] || t.format}, {GAMES[t.game] || t.game}</dd>
            <dt>Начало</dt><dd>{dateTime(t.starts_at)}</dd>
            <dt>Статус</dt><dd>{T_STATUS[t.status]}{t.round ? `, тур ${t.round}${t.rounds_total ? ` из ${t.rounds_total}` : ""}` : ""}</dd>
            <dt>Участники</dt><dd>{t.players}</dd>
          </dl>
          {isEdh ? (
            <p className="muted small" style={{ marginTop: 16 }}>
              Партия длится 70 минут. Победитель забирает по 7% банка у каждого соперника; если победителя нет,
              каждый теряет 7% своего банка. Рассадка случайная внутри брекетов.
            </p>
          ) : null}
          {body}
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
                </li>
              ))}
            </ul>
          ) : <p className="muted">Пока никто не записался.</p>}
        </aside>
      </div>
    </>
  );
}
