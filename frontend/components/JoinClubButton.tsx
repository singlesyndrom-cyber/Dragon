"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

let mineCache: Promise<number[]> | null = null;   // один запрос /clubs/mine на всю таблицу клубов

/** Кнопка «Вступить» в списке клубов; если игрок уже в клубе - отметка «вы в клубе». */
export default function JoinClubButton({ clubId }: { clubId: number }) {
  const { me, ready } = useAuth();
  const [member, setMember] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!me) return;
    mineCache ??= api<any[]>("/clubs/mine").then((r) => r.map((c) => c.id)).catch(() => []);
    mineCache.then((ids) => setMember(ids.includes(clubId)));
  }, [me, clubId]);
  if (!ready) return null;
  if (!me) return <Link href="/login" className="small">Войти и вступить</Link>;
  if (member === null) return null;
  if (member) return <span className="badge">вы в клубе</span>;
  return (
    <span>
      <button type="button" disabled={busy} onClick={async () => {
        setBusy(true); setErr("");
        try {
          await api(`/clubs/${clubId}/join`, { method: "POST" });
          mineCache = null;
          setMember(true);
        } catch (e: any) { setErr(e?.message || "Не получилось"); } finally { setBusy(false); }
      }}>Вступить</button>
      {err ? <span className="err small"> {err}</span> : null}
    </span>
  );
}
