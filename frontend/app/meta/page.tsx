import { sget } from "@/lib/api";
import { pct, signed } from "@/lib/format";

export const metadata = { title: "Мета" };

export default async function Meta({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  for (const k of ["club_id", "game", "format", "since_days", "commander"]) if (sp[k]) qs.set(k, sp[k] as string);
  const [cmd, cards, clubs] = await Promise.all([
    sget<any>(`/meta/commanders?${qs}&min_games=5`),
    sget<any>(`/meta/cards?${qs}&limit=40`),
    sget<any[]>("/clubs"),
  ]);
  return (
    <>
      <h1>Мета</h1>
      <p className="lead">
        Считается по колодам, поданным на завершённые турниры. Перевес показывает, насколько винрейт выше
        ожидаемого: 25% за столом на четверых, 50% в матче один на один.
      </p>
      <form className="row inline" action="/meta">
        <select name="club_id" defaultValue={sp.club_id || ""} aria-label="Клуб">
          <option value="">Все клубы</option>
          {(clubs || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select name="format" defaultValue={sp.format || ""} aria-label="Формат">
          <option value="">Все форматы</option>
          <option value="edh">EDH</option>
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

      <h2>Командиры</h2>
      <p className="muted small">Колод в выборке: {cmd?.entries ?? 0}. Строки с малым числом партий приглушены: выводы по ним делать рано.</p>
      {cmd?.commanders?.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Командир</th><th className="r">Колод</th><th className="r">Доля</th><th className="r">Партий</th><th className="r">Винрейт</th><th className="r">Перевес</th></tr></thead>
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
      <p className="muted small">Доля колод, в которых встречается карта. Базовые земли и командиры не учитываются.</p>
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
    </>
  );
}
