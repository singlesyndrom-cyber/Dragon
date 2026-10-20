import Link from "next/link";
import { notFound } from "next/navigation";
import ClubActions from "@/components/ClubActions";
import CreateTournamentLink from "@/components/CreateTournamentLink";
import EventList from "@/components/EventList";
import Standings from "@/components/Standings";
import { sget } from "@/lib/api";
import { dateOnly, WEEKDAYS } from "@/lib/format";

export default async function ClubPage({ params }: { params: Promise<{ slug: string }> }) {
  const slug = decodeURIComponent((await params).slug);   // адрес может прийти уже закодированным
  const club = await sget<any>(`/clubs/${encodeURIComponent(slug)}`);
  if (!club) notFound();
  const [board, tournaments, news, seasons] = await Promise.all([
    sget<any[]>(`/clubs/${club.id}/leaderboard`),
    sget<any[]>(`/tournaments?club_id=${club.id}&limit=20`),
    sget<any[]>(`/news?club_id=${club.id}&limit=5`),
    sget<any[]>(`/leagues?club_id=${club.id}`),
  ]);
  const liveSeasons = (seasons || []).filter((s) => s.status !== "finished");
  const rows = board || [];
  const byBank = [...rows].sort((a, b) => b.edh_bank - a.edh_bank).filter((r) => r.events_played > 0);
  const upcoming = (tournaments || []).filter((t) => t.status !== "finished");
  const past = (tournaments || []).filter((t) => t.status === "finished");

  return (
    <>
      <h1>{club.name}</h1>
      <div className="split">
        <div>
          {club.description ? <p className="lead">{club.description}</p> : null}
          <dl className="facts">
            {club.city ? (<><dt>Город</dt><dd>{club.city}</dd></>) : null}
            <dt>Проведено турниров</dt><dd>{club.tournaments_total}</dd>
            <dt>Средняя явка</dt><dd>{Math.round(club.avg_participants * 10) / 10}</dd>
            {club.busiest_weekday !== null ? (<><dt>Чаще всего играют</dt><dd>{WEEKDAYS[club.busiest_weekday]}</dd></>) : null}
            <dt>Рейтинг клуба</dt><dd className="gold">{Math.round(club.rating)}</dd>
          </dl>

          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <h2>Ближайшие турниры</h2>
            <CreateTournamentLink clubId={club.id} />
          </div>
          <EventList items={upcoming} empty="Анонсов пока нет." />

          {liveSeasons.length ? (
            <>
              <h2>Сезоны лиги</h2>
              <ul className="news-list">
                {liveSeasons.map((s) => (
                  <li key={s.id} style={{ padding: "10px 0" }}>
                    <Link href={`/leagues/${s.id}`}>{s.name}</Link>{" "}
                    <span className="muted small">
                      {s.kind === "edh" ? "EDH" : "Берсерк"}, {dateOnly(s.starts_on)} — {dateOnly(s.ends_on)}
                      {s.status === "upcoming" ? ", скоро" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          <h2>Лига клуба</h2>
          <Standings head={["Очки", "Ивентов"]} empty="Таблица заполнится после первого турнира."
            rows={rows.filter((r) => r.events_played > 0).map((r, i) => ({ rank: i + 1, name: r.nickname, cells: [r.league_points, r.events_played] }))} />

          {byBank.length ? (
            <>
              <h2>Банк EDH</h2>
              <Standings head={["Банк"]}
                rows={byBank.map((r, i) => ({ rank: i + 1, name: r.nickname, cells: [Math.round(r.edh_bank).toLocaleString("ru-RU")] }))} />
            </>
          ) : null}

          {past.length ? (<><h2>Прошедшие турниры</h2><EventList items={past} empty="" /></>) : null}
        </div>
        <aside>
          <ClubActions clubId={club.id} />
          <h3 style={{ marginTop: 24 }}>Новости клуба</h3>
          {news?.length ? (
            <ul className="news-list">
              {news.map((a) => (
                <li key={a.id} style={{ padding: "10px 0" }}>
                  <Link href={`/news/${a.slug}`}>{a.title}</Link>
                  <div className="muted small">{dateOnly(a.published_at)}</div>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Новостей пока нет.</p>}
        </aside>
      </div>
    </>
  );
}
