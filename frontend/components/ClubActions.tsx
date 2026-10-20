"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ClubActions({ clubId }: { clubId: number }) {
  const { me, ready } = useAuth();
  const router = useRouter();
  const [m, setM] = useState<any>(null);
  const { busy, error, run } = useAction();

  useEffect(() => {
    if (me) api(`/clubs/${clubId}/membership`).then(setM).catch(() => setM(null));
  }, [me, clubId]);

  if (!ready) return null;
  if (!me) return <div className="panel"><Link href="/login">Войдите</Link>, чтобы вступить в клуб.</div>;
  if (!m) return null;

  return (
    <div className="panel stack">
      {m.member ? (
        <>
          <div className="muted small">Ваш банк EDH в этом клубе</div>
          <div className="bank num">{Math.round(m.edh_bank).toLocaleString("ru-RU")}</div>
          <div className="muted small">Очки лиги: {m.league_points}</div>
        </>
      ) : (
        <button className="primary" disabled={busy}
          onClick={() => run(() => api(`/clubs/${clubId}/join`, { method: "POST" })).then((ok) => {
            if (ok) { api(`/clubs/${clubId}/membership`).then(setM); router.refresh(); }
          })}>
          Вступить в клуб
        </button>
      )}
      {m.can_manage ? <Link href={`/manage/clubs/${clubId}`} className="btn">Управление клубом</Link> : null}
      <Status error={error} />
    </div>
  );
}
