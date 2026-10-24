import Link from "next/link";
import BerserkMeta from "@/components/BerserkMeta";
import { sget } from "@/lib/api";
import { GAME_LIST, pct, signed } from "@/lib/format";

export const metadata = { title: "Мета" };

export default async function Meta({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const game = sp.game === "berserk" || sp.game === "response" ? sp.game : "mtg";      // у каждой игры своя мета, без смешивания
  const rs = game === "response";            // у «Респонса» колоду возглавляет герой - мета по героям
  const qs = new URLSearchParams({ game });
  for (const k of ["club_id", "format", "since_days", "commander"]) if (sp[k]) qs.set(k, sp[k] as string);
  const tabs = (
    <div className="tabs" role="tablist">
      {GAME_LIST.map(([g, l]) => {
        const q = new URLSearchParams({ game: g });
        for (const k of ["club_id", "since_days"]) if (sp[k]) q.set(k, sp[k] as string);
        return <Link key={g} href={`/meta?${q}`} role="tab" aria-selected={game === g} className={game === g ? "on" : ""}>{l}</Link>;
      })}
    </div>
  );
  const filters = (clubs: any[] | null) => (
    <form className="row inline" action="/meta">
      <input type="hidden" name="game" value={game} />
      <select name="club_id" defaultValue={sp.club_id || ""} aria-label="Клуб">
        <option value="">Все клубы</option>
        {(clubs || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <select name="format" defaultValue={sp.format || ""} aria-label="Формат">
        <option value="">Все форматы</option>
        {game === "mtg" ? <option value="edh">EDH</option> : null}
        <option value="swiss">Швейцарка</option>
        <option value="fast_swiss">Быстрый швейцарец</option>
      </select>
      <select name="since_days" defaultValue={sp.since_days || "90"} aria-label="Период">
        <option value="30">30 дней</option>
        <option value="90">90 дней</option>
        <option value="365">Год</option>
      </select>
      <button>Показать</button>
    </form>
  );
  if (game === "berserk") {
    const [bk, clubs] = await Promise.all([sget<any>(`/meta/berserk?${qs}`), sget<any[]>("/clubs")]);
    return (
      <>
        <h1>Мета</h1>
        {tabs}
        <p className="lead">
          «Берсерк»: связки стихий и архетипы по колодам с завершённых турниров клубов. Перевес — насколько винрейт
          выше ожидаемых 50% в матче один на один.
        </p>
        {filters(clubs)}
        {bk ? <BerserkMeta bk={bk} /> : <p className="muted">Данных пока нет.</p>}
        <h2>Мета-стейплы</h2>
        <p className="muted small">Доля турнирных колод, в которых встречается карта.</p>
        {bk?.cards?.cards?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Карта</th><th className="r">Колод</th><th className="r">Доля колод</th></tr></thead>
              <tbody>{bk.cards.cards.map((c: any) => (
                <tr key={c.card}><td>{c.card}</td><td className="r">{c.decks}</td><td className="r">{c.usage_pct.toLocaleString("ru-RU")}%</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="muted">Данных пока нет.</p>}
      </>
    );
  }
  const poolQs = new URLSearchParams({ game, limit: "20" });
  if (sp.club_id) poolQs.set("club_id", sp.club_id);
  const [cmd, cards, clubs, pool] = await Promise.all([
    sget<any>(`/meta/commanders?${qs}&min_games=5`),
    sget<any>(`/meta/cards?${qs}&limit=40`),
    sget<any[]>("/clubs"),
    sget<any>(`/meta/pool?${poolQs}`),
  ]);
  return (
    <>
      <h1>Мета</h1>
      {tabs}
      <p className="lead">
        Считается по колодам, поданным на завершённые турниры. Перевес показывает, насколько винрейт выше
        ожидаемого: 25% за столом на четверых, 50% в матче один на один.
      </p>
      {filters(clubs)}

      <h2>{rs ? "Герои" : "Командиры"}</h2>
      <p className="muted small">Колод в выборке: {cmd?.entries ?? 0}. Строки с малым числом партий приглушены: выводы по ним делать рано.</p>
      {cmd?.commanders?.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{rs ? "Герой" : "Командир"}</th><th className="r">Колод</th><th className="r">Доля</th><th className="r">Партий</th><th className="r">Винрейт</th><th className="r">Перевес</th></tr></thead>
            <tbody>
              {cmd.commanders.map((c: any) => (
                <tr key={c.commander} style={c.reliable ? undefined : { opacity: 0.55 }}>
                  <td><a href={`/meta?${new URLSearchParams({ ...Object.fromEntries(qs), commander: c.commander })}`}>{c.commander}</a></td>
                  <td className="r">{c.decks}</td>
                  <td className="r">{pct(c.pick_rate)}</td>
                  <td className="r">{c.games}</td>
                  <td className="r">{pct(c.win_rate)}</td>
                  <td className={"r " + (c.edge > 0 ? "win" : c.edge < 0 ? "loss" : "")}>{c.edge === null ? "—" : signed(c.edge * 100) + " п.п."}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Данных пока нет.</p>}

      <h2>{sp.commander ? `Стейплы: ${sp.commander}` : "Мета-стейплы"}</h2>
      <p className="muted small">Доля колод, в которых встречается карта. {rs ? "Герои не учитываются." : "Базовые земли и командиры не учитываются."}</p>
      {cards?.cards?.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Карта</th><th className="r">Колод</th><th className="r">Доля колод</th></tr></thead>
            <tbody>
              {cards.cards.map((c: any) => (
                <tr key={c.card}><td>{c.card}</td><td className="r">{c.decks}</td><td className="r">{c.usage_pct.toLocaleString("ru-RU")}%</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Данных пока нет.</p>}
      <h2>Популярное у игроков</h2>
      <p className="muted small">
        Колоды из пулов игроков{sp.club_id ? " этого клуба" : ""}, которые владельцы отметили «в мете» в личном кабинете
        (без имён и без результатов — только что собирают). Колод: {pool?.decks ?? 0}.
      </p>
      {pool?.decks ? (
        <div className="split">
          <div className="table-wrap">
            <table>
              <thead><tr><th>{rs ? "Герой" : "Командир"}</th><th className="r">Колод</th><th className="r">Доля</th></tr></thead>
              <tbody>
                {pool.commanders.map((c: any) => (
                  <tr key={c.commander}><td>{c.commander}</td><td className="r">{c.decks}</td><td className="r">{pct(c.pick_rate)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Карта</th><th className="r">Доля колод</th></tr></thead>
              <tbody>
                {pool.cards.map((c: any) => (
                  <tr key={c.card}><td>{c.card}</td><td className="r">{c.usage_pct.toLocaleString("ru-RU")}%</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : <p className="muted">Пока никто не добавил колоды в мету. Отметьте свои колоды «в мете» в <a href="/me#decks">личном кабинете</a>.</p>}
    </>
  );
}
