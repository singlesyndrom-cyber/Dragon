"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function NewClub() {
  const { me, ready } = useAuth();
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [f, setF] = useState({ name: "", city: "", description: "" });

  if (ready && !me) return <p><Link href="/login">Войдите</Link>, чтобы создать клуб.</p>;
  if (ready && me && !me.is_club_creator) {
    return (
      <>
        <h1>Новый клуб</h1>
        <p className="lead">Создавать клубы могут игроки со статусом «Создатель Клуба».</p>
        <p>Подайте заявку в <Link href="/me#creator">личном кабинете</Link>: администратор рассмотрит её, и после одобрения здесь откроется форма создания клуба.</p>
      </>
    );
  }
  return (
    <>
      <h1>Новый клуб</h1>
      <p className="lead">Вы станете организатором: сможете создавать турниры, вести лигу и публиковать новости клуба.</p>
      <form onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await api("/clubs", { body: f });
          router.push(`/clubs/${r.slug}`);
        });
      }}>
        <label><span>Название</span><input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label><span>Город</span><input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></label>
        <label><span>Описание</span><textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <button className="primary" disabled={busy}>Создать клуб</button>
        <Status error={error} />
      </form>
    </>
  );
}
