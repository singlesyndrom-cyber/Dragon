"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

export default function ForgotForm() {
  const [email, setEmail] = useState("");
  // email, набранный на странице входа, - без передачи через адресную строку
  useEffect(() => {
    try { const v = window.sessionStorage.getItem("forgot_email"); if (v) setEmail(v); } catch {}
  }, []);
  const [sent, setSent] = useState("");
  const { busy, error, run } = useAction();

  if (sent) {
    return (
      <>
        <h1>Проверьте почту</h1>
        <div className="panel narrow">
          <p style={{ marginTop: 0 }}>Если аккаунт с адресом <b>{sent}</b> есть, мы отправили на него письмо со ссылкой для нового пароля. Ссылка действует час и сработает один раз.</p>
          <p className="small muted">Если к аккаунту привязан Telegram, ссылка придёт и от бота. Письма нет несколько минут — загляните в «Спам».</p>
          <p className="small" style={{ marginBottom: 0 }}><button className="link-btn" onClick={() => setSent("")}>Отправить ещё раз</button> · <Link href="/login">Вернуться ко входу</Link></p>
        </div>
      </>
    );
  }

  return (
    <>
      <h1>Восстановление пароля</h1>
      <form className="narrow" onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          await api("/auth/password/forgot", { body: { email } });
          setSent(email.trim());
        });
      }}>
        <p className="muted" style={{ marginTop: 0 }}>Укажите email, с которым вы регистрировались. Пришлём ссылку, по которой можно задать новый пароль.</p>
        <label><span>Email</span><input type="email" required autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <button className="primary" disabled={busy}>Прислать ссылку</button>
        <Status error={error} />
        <p className="section small">Вспомнили пароль? <Link href="/login">Войти</Link></p>
      </form>
    </>
  );
}
