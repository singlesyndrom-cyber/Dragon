import Link from "next/link";
import { sget } from "@/lib/api";
import { dateOnly } from "@/lib/format";

export const metadata = { title: "Лиги" };

const KIND: Record<string, string> = { edh: "EDH, банк сезона", berserk: "Берсерк, очки за турниры" };

export default async function Leagues() {
  const all = (await sget<any[]>("/leagues")) || [];
  const groups: [string, any[]][] = [
    ["Идут сейчас", all.filter((l) => l.status === "active")],
    ["Скоро начнутся", all.filter((l) => l.status === "upcoming")],
    ["Завершённые сезоны", all.filter((l) => l.status === "finished")],
  ];
  return (
    <>
      <h1>Лиги</h1>
      <p className="lead">
        Сезон длится 1–3 месяца и складывается из еженедельных ивентов клуба. В EDH у каждого свой банк сезона
        (старт 1000), в «Берсерке» суммируются очки турниров.
      </p>
      {all.length ? groups.filter(([, items]) => items.length).map(([title, items]) => (
        <section key={title}>
          <h2>{title}</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Сезон</th><th>Клуб</th><th>Формат</th><th>Даты</th><th className="r">Ивентов</th></tr></thead>
              <tbody>
                {items.map((l) => (
                  <tr key={l.id}>
                    <td><Link href={`/leagues/${l.id}`}>{l.name}</Link></td>
                    <td><Link href={`/clubs/${l.club_slug}`}>{l.club}</Link></td>
                    <td>{KIND[l.kind]}</td>
                    <td className="num">{dateOnly(l.starts_on)} — {dateOnly(l.ends_on)}</td>
                    <td className="r">{l.events}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )) : <p className="muted">Сезонов пока нет. Организатор клуба создаёт сезон в «Управлении клубом».</p>}
    </>
  );
}

