"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ResetForm({ token }: { token: string }) {
  const { signIn } = useAuth();
  const router = useRouter();
  const { busy, error, run, setError } = useAction();
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");

  // убираем токен из адресной строки и истории браузера: ссылка одноразовая, светить её незачем
  useEffect(() => {
    if (token) try { window.history.replaceState(null, "", "/reset"); } catch {}
  }, [token]);

  if (!token) {
    return (
      <>
        <h1>Новый пароль</h1>
        <p>Ссылка неполная. Откройте её из письма целиком или <Link href="/forgot">запросите новую</Link>.</p>
      </>
    );
  }

  return (
    <>
      <h1>Новый пароль</h1>
      <form className="narrow" onSubmit={(e) => {
        e.preventDefault();
        if (password !== repeat) { setError("Пароли не совпадают"); return; }
        run(async () => {
          const r = await api("/auth/password/reset", { body: { token, password } });
          await signIn(r.access_token);
          router.push("/me");
        });
      }}>
        <label><span>Новый пароль, не короче 8 символов</span><input type="password" required minLength={8} autoComplete="new-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <label><span>Повторите пароль</span><input type="password" required minLength={8} autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} /></label>
        <button className="primary" disabled={busy}>Сохранить и войти</button>
        <Status error={error} />
        {error.includes("Запросите новую") ? <p className="small"><Link href="/forgot">Запросить новую ссылку</Link></p> : null}
        <p className="hint">После смены пароля другие устройства выйдут из аккаунта.</p>
      </form>
    </>
  );
}
