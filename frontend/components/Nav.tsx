"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

// основные разделы - всегда в строке; остальные на широком экране под «Ещё», на телефоне - в той же прокручиваемой строке
const MAIN = [
  ["/tournaments", "Турниры"],
  ["/play", "За столом"],
  ["/ratings", "Рейтинг"],
  ["/clubs", "Клубы"],
  ["/decks", "Колоды"],
  ["/meta", "Мета"],
] as const;
const MORE = [
  ["/cards", "Картотека"],
  ["/leagues", "Лиги"],
  ["/news", "Новости"],
  ["/auctions", "Аукцион"],
] as const;

export default function Nav() {
  const path = usePathname();
  const { me, ready, signOut } = useAuth();
  return (
    <header className="top">
      <div className="wrap">
        <Link href="/" className="brand"><img src="/icon-192.png" alt="" width={32} height={32} />Dragon</Link>
        <nav className="nav" aria-label="Разделы">
          {MAIN.map(([href, label]) => (
            <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined}>{label}</Link>
          ))}
          {MORE.map(([href, label]) => (
            <Link key={href} href={href} className="nav-sec" aria-current={path.startsWith(href) ? "page" : undefined}>{label}</Link>
          ))}
          <details className="nav-more" key={path}>
            <summary className={MORE.some(([h]) => path.startsWith(h)) ? "on" : undefined}>Ещё</summary>
            <div className="nav-menu">
              {MORE.map(([href, label]) => (
                <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined}>{label}</Link>
              ))}
            </div>
          </details>
        </nav>
        <div className="who">
          {!ready ? null : me ? (
            <>
              {me.role === "admin" ? <Link href="/admin">Админка</Link> : me.is_moderator ? <Link href="/admin">Модерация</Link> : null}
              {me.is_publisher && me.role !== "admin" ? <Link href="/publisher">Издатель</Link> : null}
              <Link href="/me" className="nick" title={me.nickname}>{me.nickname}</Link>
              <button className="link-btn" onClick={signOut}>Выйти</button>
            </>
          ) : (
            <>
              <Link href="/login">Войти</Link>
              <Link href="/register" className="btn primary">Регистрация</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
