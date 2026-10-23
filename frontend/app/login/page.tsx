"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { Status, useAction } from "@/components/Form";
import TelegramLogin from "@/components/TelegramLogin";
import VkButton from "@/components/VkButton";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function Login() {
  const { signIn } = useAuth();
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const onTelegram = useCallback((data: Record<string, unknown>) => {
    run(async () => {
      const r = await api("/auth/telegram", { body: data });
      await signIn(r.access_token);
      router.push("/me");
    });
  }, [run, signIn, router]);

  return (
    <>
      <h1>Вход</h1>
      <div className="split">
        <form onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            const r = await api("/auth/login", { body: { email, password } });
            await signIn(r.access_token);
            router.push("/me");
          });
        }}>
          <label><span>Email</span><input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>
            <span className="label-row">Пароль <Link href="/forgot" className="small"
              onClick={() => { try { window.sessionStorage.setItem("forgot_email", email); } catch {} }}>Забыли пароль?</Link></span>
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button className="primary" disabled={busy}>Войти</button>
          <Status error={error} />
          <p className="section">Нет аккаунта? <Link href="/register">Зарегистрируйтесь</Link></p>
        </form>
        <aside>
          <h3>Через Telegram</h3>
          <p className="muted small">Тот же аккаунт, что у бота: ставки на аукционе и уведомления привяжутся автоматически.</p>
          <TelegramLogin onAuth={onTelegram} />
          <div className="section" style={{ marginTop: 24 }}>
            <VkButton purpose="login" label="Войти через VK" />
          </div>
        </aside>
      </div>
    </>
  );
}
