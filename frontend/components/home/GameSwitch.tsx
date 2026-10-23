"use client";

import Link from "next/link";
import { GAME_COOKIE, HOME_GAMES, type HomeGame } from "@/lib/home";

/** Переключатель игры: вся главная показывает одну игру. Выбор запоминается в cookie, чтобы
 *  сервер сразу отдавал нужную игру при следующем заходе. */
export default function GameSwitch({ game }: { game: HomeGame }) {
  const remember = (g: HomeGame) => {
    try { document.cookie = `${GAME_COOKIE}=${g}; path=/; max-age=31536000; samesite=lax`; } catch {}
  };
  return (
    <div className="h-switch" role="group" aria-label="Игра">
      {HOME_GAMES.map(([g, label]) => (
        <Link key={g} href={`/?game=${g}`} scroll={false} aria-current={game === g ? "true" : undefined}
          className={game === g ? "on" : ""} onClick={() => remember(g)}>{label}</Link>
      ))}
    </div>
  );
}
