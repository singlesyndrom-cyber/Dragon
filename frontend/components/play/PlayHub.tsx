"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { type CurrentMatch, type Outcome, outcomeOf, scoreText } from "@/lib/play";
import LifeCounter from "./LifeCounter";
import MatchCard from "./MatchCard";
import SquadBuilder from "./SquadBuilder";

type Tab = "mtg" | "berserk";
const TAB_KEY = "dragon_play_tab";

/** «За столом»: текущий матч в турнире + инструменты партии. Работает и как приложение на телефоне. */
export default function PlayHub() {
  const { me } = useAuth();
  const [tab, setTab] = useState<Tab>("mtg");
  const [match, setMatch] = useState<CurrentMatch | null>(null);
  const [suggest, setSuggest] = useState<{ outcome: Outcome; score: string } | null>(null);

  useEffect(() => { try { const t = window.localStorage.getItem(TAB_KEY); if (t === "mtg" || t === "berserk") setTab(t); } catch {} }, []);
  const choose = (t: Tab) => { setTab(t); try { window.localStorage.setItem(TAB_KEY, t); } catch {} };
  const onMatch = useCallback((m: CurrentMatch | null) => {
    setMatch(m);
    if (m && (m.tournament.game === "mtg" || m.tournament.game === "berserk")) setTab(m.tournament.game as Tab);
  }, []);
  const onScore = useCallback((g: [number, number, number]) => {
    setSuggest(g[0] >= 2 || g[1] >= 2 ? { outcome: outcomeOf(g), score: scoreText(g) } : null);
  }, []);

  return (
    <div className="play">
      <h1>За столом</h1>
      <MatchCard suggest={suggest} onMatch={onMatch} />
      <nav className="tabs" role="tablist" aria-label="Игра">
        <button type="button" role="tab" aria-selected={tab === "mtg"} className={tab === "mtg" ? "on" : ""} onClick={() => choose("mtg")}>Magic — жизни</button>
        <button type="button" role="tab" aria-selected={tab === "berserk"} className={tab === "berserk" ? "on" : ""} onClick={() => choose("berserk")}>Берсерк — набор отряда</button>
      </nav>
      {tab === "mtg" ? (
        <LifeCounter me={match && !match.bye && match.tournament.game === "mtg" ? me?.nickname : undefined}
          opponent={match && match.tournament.game === "mtg" ? match.opponent?.nickname : undefined} onMatch={onScore} />
      ) : <SquadBuilder />}
      <p className="muted small" style={{ marginTop: 24 }}>Счётчики работают без интернета. Чтобы установить как приложение:
        Android — меню Chrome → «Установить приложение»; iPhone — Safari → «Поделиться» → «На экран „Домой“».</p>
    </div>
  );
}
