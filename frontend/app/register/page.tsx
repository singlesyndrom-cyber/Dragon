"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function Register() {
  const { signIn } = useAuth();
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [f, setF] = useState({ nickname: "", email: "", password: "" });
  return (
    <>
      <h1>Регистрация</h1>
      <form onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await api("/auth/register", { body: f });
          await signIn(r.access_token);
          router.push("/me");
        });
      }}>
        <label><span>Ник — так вас увидят в таблицах</span><input required minLength={2} maxLength={64} value={f.nickname} onChange={(e) => setF({ ...f, nickname: e.target.value })} /></label>
        <label><span>Email</span><input type="email" required autoComplete="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label><span>Пароль, не короче 8 символов</span><input type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
        <button className="primary" disabled={busy}>Создать аккаунт</button>
        <Status error={error} />
        <p className="section">Уже есть аккаунт? <Link href="/login">Войдите</Link></p>
      </form>
    </>
  );
}
