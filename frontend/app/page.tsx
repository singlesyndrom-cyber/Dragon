import Link from "next/link";
import EventList, { type TournamentRow } from "@/components/EventList";
import { sget } from "@/lib/api";
import { dateOnly, rub } from "@/lib/format";

export default async function Home() {
  const [running, upcoming, news, lots] = await Promise.all([
    sget<TournamentRow[]>("/tournaments?status=running&limit=10"),
    sget<TournamentRow[]>("/tournaments?status=registration&limit=12"),
    sget<any[]>("/news?limit=4"),
    sget<any[]>("/auctions/lots?limit=4"),
  ]);
  const events = [...(running || []), ...(upcoming || [])];
  return (
    <>
      <h1>Где сегодня играют</h1>
      <p className="lead">
        Турниры клубов и магазинов по Magic: The Gathering, EDH и «Берсерку». Запишитесь на ивент, подайте деклист
        и следите за таблицей прямо с телефона.
      </p>
      <EventList items={events} empty="Открытых турниров пока нет. Загляните в раздел клубов — там видно, кто и когда собирается." />

      <div className="split section">
        <section>
          <h2>Новости</h2>
          {news?.length ? (
            <ul className="news-list">
              {news.map((a) => (
                <li key={a.id}>
                  <h3><Link href={`/news/${a.slug}`}>{a.title}</Link></h3>
                  <span className="muted small">{a.club || "Dragon"}, {dateOnly(a.published_at)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Новостей пока нет.</p>}
          <p><Link href="/news">Все новости</Link></p>
        </section>
        <section>
          <h2>На аукционе</h2>
          {lots?.length ? (
            <ul className="news-list">
              {lots.map((l) => (
                <li key={l.id}>
                  <Link href={`/auctions/${l.id}`}>{l.title}</Link>
                  <div className="muted small num">{l.current_price ? rub(l.current_price) : `старт ${rub(l.start_price)}`}, {l.condition}</div>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Активных лотов нет. Выставить карту можно через Telegram-бота командой /sell.</p>}
          <p><Link href="/auctions">Все лоты</Link></p>
        </section>
      </div>
    </>
  );
}
