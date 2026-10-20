import Link from "next/link";
import { dateTime, FORMATS, GAMES, plural } from "@/lib/format";

export type TournamentRow = {
  id: number; name: string; club: string | null; club_slug: string | null; game: string; format: string;
  status: string; starts_at: string; players: number | null; round: number; rounds_total: number | null;
};

export default function EventList({ items, empty }: { items: TournamentRow[]; empty: string }) {
  if (!items.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="events">
      {items.map((t) => (
        <li key={t.id}>
          <Link href={`/tournaments/${t.id}`}>
            <span className="when">{t.status === "running" ? "Идёт сейчас" : dateTime(t.starts_at)}</span>
            <span>
              <span className="title">{t.name}</span>
              <br />
              <span className="meta">{t.club}, {FORMATS[t.format] || t.format}, {GAMES[t.game] || t.game}</span>
            </span>
            <span className="count num">
              {t.players ?? 0} {plural(t.players ?? 0, "игрок", "игрока", "игроков")}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
