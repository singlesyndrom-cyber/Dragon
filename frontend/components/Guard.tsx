"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

/** Показывает содержимое только вошедшим (и, если нужно, только админам или модераторам). */
export default function Guard({ admin = false, moderator = false, children }: { admin?: boolean; moderator?: boolean; children: React.ReactNode }) {
  const { me, ready } = useAuth();
  if (!ready) return <p className="muted">Загружаем…</p>;
  if (!me) return <p><Link href="/login">Войдите</Link>, чтобы открыть этот раздел.</p>;
  if (admin && me.role !== "admin") return <p>Раздел доступен только администраторам.</p>;
  if (moderator && me.role !== "admin" && !me.is_moderator) return <p>Раздел доступен только администраторам и модераторам.</p>;
  return <>{children}</>;
}
