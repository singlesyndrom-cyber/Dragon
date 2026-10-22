import Link from "next/link";
import JoinClubButton from "@/components/JoinClubButton";
import { sget } from "@/lib/api";
import { WEEKDAYS } from "@/lib/format";

export const metadata = { title: "Клубы" };

export default async function Clubs() {
  const clubs = (await sget<any[]>("/clubs")) || [];
  const sorted = [...clubs].sort((a, b) => b.rating - a.rating);
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Клубы и магазины</h1>
        <Link href="/clubs/new" className="btn">Добавить клуб</Link>
      </div>
      <p className="lead" style={{ marginTop: 0 }}>
        Вступите в клуб, чтобы записываться на его турниры в один клик, бронировать столы и попадать в лигу клуба.
      </p>
      {sorted.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Клуб</th><th>Город</th><th className="r">Турниров</th><th className="r">Средняя явка</th><th>Чаще играют</th><th className="r">Рейтинг</th><th></th></tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.id}>
                  <td><Link href={`/clubs/${c.slug}`}>{c.name}</Link></td>
                  <td>{c.city || <span className="muted">—</span>}</td>
                  <td className="r">{c.tournaments_total}</td>
                  <td className="r">{Math.round(c.avg_participants * 10) / 10}</td>
                  <td>{c.busiest_weekday !== null ? WEEKDAYS[c.busiest_weekday] : <span className="muted">—</span>}</td>
                  <td className="r gold">{Math.round(c.rating)}</td>
                  <td className="r"><JoinClubButton clubId={c.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Клубов пока нет. Создайте первый — вы станете его организатором.</p>}
    </>
  );
}
