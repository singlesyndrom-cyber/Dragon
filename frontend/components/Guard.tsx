"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

/** Показывает содержимое только вошедшим (и, если нужно, только админам). */
export default function Guard({ admin = false, children }: { admin?: boolean; children: React.ReactNode }) {
  const { me, ready } = useAuth();
  if (!ready) return <p className="muted">Загружаем…</p>;
  if (!me) return <p><Link href="/login">Войдите</Link>, чтобы открыть этот раздел.</p>;
  if (admin && me.role !== "admin") return <p>Раздел доступен только администраторам.</p>;
  return <>{children}</>;
}
