"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

const FEATURES: [string, string][] = [
  ["Регистрация и лист ожидания", "Места, запись игроков, напоминания в Telegram."],
  ["Паринги и результаты", "Швейцарка, рассадка по столам, таблица в реальном времени."],
  ["Драфт по правилам", "Рассадка, таймеры пиков и экран судьи."],
  ["Колоды и проверка", "Деклисты с проверкой формата, импорт NXT и .brsc."],
  ["Мета клуба", "Архетипы, доли и винрейты по вашим турнирам."],
  ["Лиги, брони, аукцион", "Сезоны с таблицей, столы на вечер, лоты игроков."],
];

/** Блок для организаторов. Тем, кто уже может создавать клубы, он не нужен. */
export default function OrgBand() {
  const { me } = useAuth();
  if (me?.is_club_creator) return null;
  return (
    <section className="h-band">
      <div className="h-band-text">
        <span className="h-kicker">Для организаторов</span>
        <h2>Проводите турниры без таблиц и бумажек</h2>
        <p className="muted">Подайте заявку — после одобрения клуб создаётся сразу. Бесплатно для клубов.</p>
        <div className="row">
          <Link href={me ? "/me#creator" : "/register"} className="btn primary big">Подать заявку на клуб</Link>
          <a href="/guides/dragon-mtg.pdf" target="_blank" rel="noopener">Путеводитель MTG (PDF)</a>
          <a href="/guides/dragon-berserk.pdf" target="_blank" rel="noopener">Путеводитель «Берсерк» (PDF)</a>
        </div>
      </div>
      <ul className="h-features">
        {FEATURES.map(([t, d]) => <li key={t}><b>{t}</b><span className="muted small">{d}</span></li>)}
      </ul>
    </section>
  );
}
