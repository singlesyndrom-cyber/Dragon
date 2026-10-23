"use client";

import { useEffect, useState } from "react";

/** Картинка карты; у двусторонних - кнопка «Перевернуть» с анимацией переворота.
 *  Кнопка внутри ссылки (плитка Картотеки) не открывает карту: клик гасится. */
export default function FlipCard({ front, back, alt, className, lazy }: {
  front?: string | null; back?: string | null; alt: string; className?: string; lazy?: boolean;
}) {
  const [flipped, setFlipped] = useState(false);
  useEffect(() => setFlipped(false), [front]);
  if (!front) return null;
  if (!back) return <img src={front} alt={alt} className={className} loading={lazy ? "lazy" : undefined} decoding="async" />;
  return (
    <span className={`flipcard ${flipped ? "is-flipped" : ""} ${className || ""}`}>
      <span className="flip-inner">
        <img src={front} alt={alt} className="flip-face" loading={lazy ? "lazy" : undefined} decoding="async" aria-hidden={flipped} />
        <img src={back} alt={`${alt} — обратная сторона`} className="flip-face flip-back" loading="lazy" decoding="async" aria-hidden={!flipped} />
      </span>
      <button type="button" className="flip-btn" aria-pressed={flipped}
        aria-label={flipped ? "Показать лицевую сторону" : "Перевернуть карту"} title="Перевернуть"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setFlipped(!flipped); }}>
        ↻ <span>Перевернуть</span>
      </button>
    </span>
  );
}
