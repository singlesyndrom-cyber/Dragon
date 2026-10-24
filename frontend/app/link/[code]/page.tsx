"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { rememberReturn } from "@/lib/afterLogin";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";

type Info = { provider: string; provider_name: string; who: string; already_linked: boolean;
  tournament: { id: number; name: string; starts_at: string; club: string | null } | null };

/** Подтверждение из бота: привязать Telegram/VK к номеру игрока (или создать аккаунт) и записаться на турнир. */
export default function LinkPage() {
  const { code } = useParams<{ code: string }>();
  const { me, ready, signIn } = useAuth();
  const [info, setInfo] = useState<Info | null>(null);
  const [fail, setFail] = useState("");
  const [result, setResult] = useState<{ message: string | null; player_no: number | null } | null>(null);
  const { busy, error, run } = useAction();

  useEffect(() => {
    api<Info>(`/auth/link-code/${code}`).then(setInfo).catch((e) => setFail(e.message || "Ссылка недействительна"));
  }, [code]);

  if (fail) {
    return (
      <>
        <h1>Привязка аккаунта</h1>
        <p className="lead">{fail}</p>
        <p><Link href="/tournaments">Турниры</Link> · <Link href="/me">Личный кабинет</Link></p>
      </>
    );
  }
  if (!info || !ready) return <p className="muted">Загрузка…</p>;

  const t = info.tournament;
  if (result) {
    return (
      <>
        <h1>Готово</h1>
        <p className="lead">{info.provider_name} {info.who} привязан к номеру игрока <b className="num">{result.player_no}</b>.
          Дальше кнопки «Записаться» в {info.provider === "vk" ? "беседах ВКонтакте" : "Telegram"} работают сразу.</p>
        {result.message ? <div className="panel"><p style={{ margin: 0 }}>{result.message}</p></div> : null}
        <p className="section">{t ? <><Link href={`/tournaments/${t.id}`} className="btn primary">К турниру</Link>{" "}</> : null}
          <Link href="/me" className="btn">Личный кабинет</Link></p>
      </>
    );
  }

  const claim = () => run(async () => {
    const r = await api<any>(`/auth/link-code/${code}/claim`, { method: "POST" });
    setResult({ message: r.message, player_no: r.player_no });
  });
  const create = () => run(async () => {
    const r = await api<any>(`/auth/link-code/${code}/new`, { method: "POST" });
    await signIn(r.access_token);
    setResult({ message: r.message, player_no: r.player_no });
  });

  return (
    <>
      <h1>Связать {info.provider_name} с номером игрока</h1>
      <p className="lead">Вы нажали «Записаться» из {info.provider_name} {info.who ? <b>{info.who}</b> : null}.
        Чтобы турниры, рейтинг и колоды были на одном номере игрока, свяжите {info.provider_name} с вашим аккаунтом на сайте.</p>
      {t ? (
        <div className="panel">
          <span className="muted small">Турнир</span>
          <h3 style={{ margin: "2px 0" }}>{t.name}</h3>
          <span className="muted small">{dateTime(t.starts_at)}{t.club ? ` · клуб «${t.club}»` : ""}</span>
        </div>
      ) : null}
      {me ? (
        <div className="stack section">
          <p>Вы вошли как <b>{me.nickname}</b>{me.player_no ? <> (номер игрока <b className="num">{me.player_no}</b>)</> : null}.</p>
          <button className="primary" disabled={busy} onClick={claim}>
            Привязать {info.provider_name}{t ? " и записаться" : ""}
          </button>
          <p className="hint">Не ваш аккаунт? Выйдите в шапке сайта и войдите в свой — ссылка останется рабочей.</p>
        </div>
      ) : (
        <div className="split section">
          <div className="stack">
            <h3 style={{ marginTop: 0 }}>У меня есть аккаунт</h3>
            <p className="muted small">Войдите — вернём вас сюда, останется нажать одну кнопку.</p>
            <div className="row">
              <Link href="/login" className="btn primary" onClick={() => rememberReturn(`/link/${code}`)}>Войти</Link>
            </div>
          </div>
          <div className="stack">
            <h3 style={{ marginTop: 0 }}>Аккаунта нет</h3>
            <p className="muted small">Создадим аккаунт по {info.provider_name} с новым номером игрока{t ? " и сразу запишем на турнир" : ""}.
              Email и пароль можно добавить потом в кабинете.</p>
            <button disabled={busy} onClick={create}>Создать аккаунт{t ? " и записаться" : ""}</button>
          </div>
        </div>
      )}
      <Status error={error} />
    </>
  );
}
