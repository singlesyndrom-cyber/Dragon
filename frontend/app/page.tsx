import Link from "next/link";
import { cookies } from "next/headers";
import GameSwitch from "@/components/home/GameSwitch";
import HomeHero from "@/components/home/HomeHero";
import OrgBand from "@/components/home/OrgBand";
import WeekList from "@/components/home/WeekList";
import { sget } from "@/lib/api";
import { dateOnly, pct, plural, rub } from "@/lib/format";
import { dayLabel, formatLabel, GAME_COOKIE, homeGame, timeOf, type HomeEvent, type HomeGame } from "@/lib/home";

type MetaRow = { name: string; decks: number; share: number; games: number; win_rate: number | null; edge: number | null; reliable: boolean };
type SeasonRow = { user_id: number; nickname: string | null; player_no: number | null; value: number; events: number; place: number };
type Home = {
  game: HomeGame; now: string; events: HomeEvent[];
  meta: { since_days: number; decks: number; rows: MetaRow[] };
  season: { id: number; name: string; kind: string; club: string; ends_on: string; players: number; rows: SeasonRow[] } | null;
  clubs: { id: number; name: string; slug: string; city: string | null; games: string[];
    next: { id: number; name: string; starts_at: string; status: string; format: string; draft: boolean } | null }[];
};

const GAME_SHORT: Record<string, string> = { mtg: "Magic", berserk: "Берсерк", response: "Респонс" };

export default async function HomePage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const game: HomeGame = homeGame(sp.game) || homeGame((await cookies()).get(GAME_COOKIE)?.value) || "mtg";
  const [h, news, lots] = await Promise.all([
    sget<Home>(`/home?game=${game}`),
    sget<any[]>("/news?limit=3"),
    sget<any[]>("/auctions/lots?limit=3"),
  ]);
  const now = h?.now || new Date().toISOString();
  const events = h?.events || [];
  const next = events.find((e) => e.status === "registration") || events[0] || null;
  const meta = h?.meta;
  const season = h?.season;

  return (
    <div className="home">
      <div className="h-switch-row"><GameSwitch game={game} /></div>

      <HomeHero game={game} next={next} now={now} />

      <section>
        <div className="h-head"><h2>Сегодня и на неделе</h2><Link href="/tournaments">Всё расписание →</Link></div>
        <WeekList events={events} now={now} />
      </section>

      <div className="h-two">
        <section className="h-card">
          <div className="h-head">
            <h2>Мета {meta?.since_days === 90 ? "за 3 месяца" : "месяца"}</h2>
            <span className="muted small">{meta?.decks ? `${meta.decks} ${plural(meta.decks, "колода", "колоды", "колод")} с турниров` : "клубные турниры"}</span>
          </div>
          {meta?.rows.length ? (
            <table className="h-meta">
              <thead><tr><th>Архетип</th><th>Доля</th><th className="num">Винрейт</th></tr></thead>
              <tbody>
                {meta.rows.map((r, i) => (
                  <tr key={r.name}>
                    <td><span className="muted num">{i + 1}</span> {r.name}</td>
                    <td><span className="h-share"><span className="h-bar" aria-hidden="true"><span style={{ width: `${Math.round(r.share * 100)}%` }} /></span><span className="num small">{pct(r.share)}</span></span></td>
                    <td className="num">{r.win_rate === null ? <span className="muted">—</span>
                      : <span className={!r.reliable ? "muted" : (r.edge ?? 0) >= 0 ? "win" : "loss"} title={r.reliable ? undefined : "Мало партий для выводов"}>{pct(r.win_rate)}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">Мета появится после первых завершённых турниров с колодами.</p>}
          <Link href={`/meta?game=${game}`}>Полная мета и стейплы →</Link>
        </section>

        <section className="h-card">
          <div className="h-head">
            <h2>Рейтинг сезона</h2>
            {season ? <span className="muted small">{season.name} · «{season.club}»</span> : null}
          </div>
          {season?.rows.length ? (
            <ol className="h-season">
              {season.rows.map((r) => (
                <li key={r.user_id}>
                  <b className="gold num">{r.place}</b>
                  <span className="h-grow">{r.player_no ? <Link href={`/players/${r.player_no}`}>{r.nickname}</Link> : r.nickname}
                    {r.player_no ? <span className="muted small"> № {r.player_no}</span> : null}</span>
                  <span className="muted small">{r.events} {plural(r.events, "турнир", "турнира", "турниров")}</span>
                  <b className="num">{r.value}</b>
                </li>
              ))}
            </ol>
          ) : <p className="muted">{season ? "Таблица заполнится после первого турнира сезона."
            : game === "response" ? "Сезоны лиги для «Респонса» появятся позже — пока смотрите рейтинг силы." : `Активного сезона по ${game === "mtg" ? "EDH" : "«Берсерку»"} сейчас нет.`}</p>}
          <Link href={season ? `/leagues/${season.id}` : "/leagues"}>{season ? "Вся таблица →" : "Все лиги →"}</Link>
        </section>
      </div>

      <section>
        <div className="h-head"><h2>Клубы</h2><Link href="/clubs">Все клубы →</Link></div>
        {h?.clubs.length ? (
          <ul className="h-clubs">
            {h.clubs.map((c) => (
              <li key={c.id}>
                <Link href={`/clubs/${c.slug}`} className="h-card">
                  <span className="h-club-top"><span className="h-letter" aria-hidden="true">{c.name.slice(0, 1)}</span>
                    <span><b>{c.name}</b><br /><span className="muted small">{c.city || "Город не указан"}</span></span></span>
                  <span className="small">{c.next ? `Ближайший: ${c.next.status === "running" ? "идёт сейчас" : `${dayLabel(c.next.starts_at, now).toLowerCase()} ${timeOf(c.next.starts_at)}`}, ${formatLabel({ ...c.next, draft_sets: null })}` : "Ближайших турниров нет"}</span>
                  {c.games.length ? <span className="muted small">{c.games.map((g) => GAME_SHORT[g] || g).join(" · ")}</span> : null}
                </Link>
              </li>
            ))}
          </ul>
        ) : <p className="muted">Клубов пока нет.</p>}
      </section>

      <OrgBand />

      <div className="h-two">
        <section>
          <div className="h-head"><h2>Новости</h2><Link href="/news">Все →</Link></div>
          {news?.length ? (
            <ul className="news-list">
              {news.map((a) => (
                <li key={a.id}>
                  <span className="muted small">{dateOnly(a.published_at)} · {a.club || "Dragon"}</span>
                  <h3><Link href={`/news/${a.slug}`}>{a.title}</Link></h3>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Новостей пока нет.</p>}
        </section>
        <section>
          <div className="h-head"><h2>Аукцион</h2><Link href="/auctions">Все лоты →</Link></div>
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
        </section>
      </div>
    </div>
  );
}
