"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** «Создать турнир» для тех, кто организует хотя бы один клуб. clubId — только для этого клуба. */
export default function CreateTournamentLink({ clubId }: { clubId?: number }) {
  const { me } = useAuth();
  const [clubs, setClubs] = useState<{ id: number; name: string }[]>([]);
  useEffect(() => {
    if (!me) { setClubs([]); return; }
    api<any[]>("/clubs/managed").then(setClubs).catch(() => setClubs([]));
  }, [me]);
  const mine = clubId ? clubs.filter((c) => c.id === clubId) : clubs;
  if (!mine.length) return null;
  if (mine.length === 1) {
    return <Link href={`/manage/clubs/${mine[0].id}#new-tournament`} className="btn primary">Создать турнир</Link>;
  }
  return (
    <details className="menu">
      <summary className="btn primary">Создать турнир</summary>
      <div className="menu-list">
        {mine.map((c) => <Link key={c.id} href={`/manage/clubs/${c.id}#new-tournament`}>{c.name}</Link>)}
      </div>
    </details>
  );
}
