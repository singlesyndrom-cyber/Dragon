import Link from "next/link";
import { cookies } from "next/headers";
import { sget } from "@/lib/api";
import { plural } from "@/lib/format";
import { GAME_COOKIE } from "@/lib/home";
import { DISCIPLINES, DISCIPLINE_NAME } from "@/lib/rating";

export const metadata = { title: "Рейтинг игроков", description: "Рейтинг силы игроков по дисциплинам: страна, города и клубы." };

type Row = { place: number; user_id: number; nickname: string; player_no: number | null; city: string | null; rating: number;
  rd: number; games: number; wins: number; draws: number; losses: number; provisional: boolean };
type City = { place: number | null; city: string; players: number; top_avg: number; top_n: number; ranked: boolean;
  events_30d: number; best: { nickname: string; player_no: number | null; rating: number } };

export default async function Ratings({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const fallback = (await cookies()).get(GAME_COOKIE)?.value === "berserk" ? "berserk_constructed" : "mtg_constructed";
  const d = sp.d && DISCIPLINE_NAME[sp.d] ? sp.d : fallback;
  const view = sp.view === "cities" ? "cities" : "players";
  const all = sp.all === "1";
  const city = (sp.city || "").trim();
  const q = new URLSearchParams({ discipline: d, limit: "200" });
  if (city) q.set("city", city);
  if (all) q.set("include_provisional", "true");
  const [board, cities, info] = await Promise.all([
    view === "players" ? sget<{ rows: Row[]; total: number }>(`/ratings?${q}`) : Promise.resolve(null),
    sget<{ cities: City[]; top: number; min_players: number }>(`/ratings/cities?discipline=${d}`),
    sget<any>("/ratings/disciplines"),
  ]);
  const href = (p: Record<string, string | undefined>) => {
    const u = new URLSearchParams();
    const m = { d, view, city: city || undefined, all: all ? "1" : undefined, ...p };
    for (const [k, v] of Object.entries(m)) if (v) u.set(k, v);
    return `/ratings?${u}`;
  };
  const rules = info?.rules;

  return (
    <>
      <h1>Рейтинг игроков</h1>
      <p className="lead">Рейтинг силы по системе Glicko-2: победа над сильным соперником даёт больше, чем над новичком.
        У каждой дисциплины свой рейтинг; «±» — насколько рейтинг точен (у тех, кто играет редко, разброс больше).</p>

      <nav className="disc-tabs" aria-label="Дисциплина">
        <span className="grp">Magic</span>
        {DISCIPLINES.filter(([, , g]) => g === "mtg").map(([k, l]) => <Link key={k} href={href({ d: k })} className={d === k ? "on" : ""} aria-current={d === k ? "page" : undefined}>{l}</Link>)}
        <span className="grp">Берсерк</span>
        {DISCIPLINES.filter(([, , g]) => g === "berserk").map(([k, l]) => <Link key={k} href={href({ d: k })} className={d === k ? "on" : ""} aria-current={d === k ? "page" : undefined}>{l}</Link>)}
      </nav>

      <div className="tabs" role="tablist">
        <Link href={href({ view: "players" })} role="tab" aria-selected={view === "players"} className={view === "players" ? "on" : ""}>Игроки</Link>
        <Link href={href({ view: "cities", city: undefined })} role="tab" aria-selected={view === "cities"} className={view === "cities" ? "on" : ""}>Города</Link>
      </div>

      {view === "players" ? (
        <>
          <form className="row inline" action="/ratings">
            <input type="hidden" name="d" value={d} />
            <select name="city" defaultValue={city} aria-label="Город">
              <option value="">Все города</option>
              {(cities?.cities || []).map((c) => <option key={c.city} value={c.city}>{c.city}</option>)}
              {city && !(cities?.cities || []).some((c) => c.city.toLowerCase() === city.toLowerCase()) ? <option value={city}>{city}</option> : null}
            </select>
            <label className="check"><input type="checkbox" name="all" value="1" defaultChecked={all} /><span>Показать предварительные</span></label>
            <button type="submit">Показать</button>
          </form>
          {board?.rows.length ? (
            <div className="table-wrap">
              <table className="rating-table">
                <thead><tr><th className="r">#</th><th>Игрок</th><th>Город</th><th className="r">Рейтинг</th><th className="r">Партий</th><th className="r">В–Н–П</th></tr></thead>
                <tbody>
                  {board.rows.map((r) => (
                    <tr key={r.user_id}>
                      <td className="r num">{r.place <= 3 && !r.provisional ? <b className="gold">{r.place}</b> : r.place}</td>
                      <td>{r.player_no ? <Link href={`/players/${r.player_no}`}>{r.nickname}</Link> : r.nickname}
                        {r.player_no ? <span className="muted small"> № {r.player_no}</span> : null}
                        {r.provisional ? <span className="badge" style={{ marginLeft: 6 }}>предв.</span> : null}</td>
                      <td>{r.city || <span className="muted">—</span>}</td>
                      <td className="r num"><b>{r.rating}</b> <span className="muted small">± {r.rd}</span></td>
                      <td className="r num">{r.games}</td>
                      <td className="r num muted">{r.wins}–{r.draws}–{r.losses}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">{all ? "Рейтинговых партий в этой дисциплине пока нет."
              : <>В таблице пока никого: игрок появляется после {rules?.provisional_games ?? 10} рейтинговых партий. <Link href={href({ all: "1" })}>Показать предварительные →</Link></>}</p>
          )}
        </>
      ) : (
        <>
          <p className="muted small">Город сравнивается по среднему рейтингу {cities?.top ?? 8} лучших активных игроков — не по сумме,
            чтобы большой город не выигрывал одним числом игроков. Место получает город, где не меньше {cities?.min_players ?? 3} игроков с основным рейтингом.</p>
          {cities?.cities.length ? (
            <div className="table-wrap">
              <table className="rating-table">
                <thead><tr><th className="r">#</th><th>Город</th><th className="r">Средний топ</th><th className="r">Игроков</th><th className="r">Турниров за 30 дней</th><th>Лучший игрок</th></tr></thead>
                <tbody>
                  {cities.cities.map((c) => (
                    <tr key={c.city}>
                      <td className="r num">{c.place ?? <span className="muted">—</span>}</td>
                      <td><Link href={href({ view: "players", city: c.city })}>{c.city}</Link></td>
                      <td className="r num"><b>{c.top_avg}</b> <span className="muted small">топ-{c.top_n}</span></td>
                      <td className="r num">{c.players}</td>
                      <td className="r num">{c.events_30d}</td>
                      <td>{c.best.player_no ? <Link href={`/players/${c.best.player_no}`}>{c.best.nickname}</Link> : c.best.nickname} <span className="muted small num">{c.best.rating}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="muted">Городов с основным рейтингом в этой дисциплине пока нет.</p>}
        </>
      )}

      <section className="panel section">
        <h2 style={{ marginTop: 0 }}>Как считается и как защищён рейтинг</h2>
        <ul>
          <li>Каждый турнир — один рейтинговый период: все партии считаются от рейтингов на начало турнира. Старт — 1500.</li>
          <li>Учитываются только завершённые турниры с результатами, не тестовые, где играли не меньше {rules?.min_players ?? 4} игроков с аккаунтами.</li>
          <li>Партии с гостями без аккаунта и пропуски тура (bye) не считаются. Партии заблокированных игроков исключаются.</li>
          <li>Одна и та же пара засчитывается не больше {rules?.pair_cap ?? 3} раз за {rules?.pair_window_days ?? 30} дней — накатать рейтинг на знакомом не выйдет.
            Исключение — региональные чемпионаты и про-туры: их назначает только администратор.</li>
          <li>В таблице игрок появляется после {rules?.provisional_games ?? 10} {plural(rules?.provisional_games ?? 10, "партии", "партий", "партий")}; кто не играл больше полугода, временно скрыт.</li>
          <li>Результаты после завершения турнира не меняются; администратор может исключить турнир из рейтинга, причина видна в карточке турнира.
            После любого такого изменения рейтинг пересчитывается заново по всей истории.</li>
          <li>Город игрока — из профиля, а если не указан — город клуба, где он сыграл больше всего турниров. Изменить: <Link href="/me#city">личный кабинет</Link>.</li>
        </ul>
      </section>
    </>
  );
}
