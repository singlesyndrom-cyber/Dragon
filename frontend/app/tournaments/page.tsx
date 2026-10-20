import CreateTournamentLink from "@/components/CreateTournamentLink";
import EventList, { type TournamentRow } from "@/components/EventList";
import { sget } from "@/lib/api";

export const metadata = { title: "Турниры" };

export default async function Tournaments() {
  const [running, upcoming, finished] = await Promise.all([
    sget<TournamentRow[]>("/tournaments?status=running"),
    sget<TournamentRow[]>("/tournaments?status=registration"),
    sget<TournamentRow[]>("/tournaments?status=finished&limit=30"),
  ]);
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Турниры</h1>
        <CreateTournamentLink />
      </div>
      {running?.length ? (<><h2>Идут сейчас</h2><EventList items={running} empty="" /></>) : null}
      <h2>Открыта регистрация</h2>
      <EventList items={upcoming || []} empty="Сейчас нет турниров с открытой регистрацией." />
      <h2>Прошедшие</h2>
      <EventList items={finished || []} empty="Завершённых турниров пока нет." />
    </>
  );
}
