"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Поле «Проверить игрока по номеру»: открывает его карточку с репутацией на аукционе. */
export default function PlayerLookup({ label = "Проверить игрока по номеру" }: { label?: string }) {
  const router = useRouter();
  const [no, setNo] = useState("");
  const clean = no.replace(/\D/g, "");
  return (
    <form className="row inline lookup" onSubmit={(e) => { e.preventDefault(); if (clean) router.push(`/players/${clean}`); }}>
      <label style={{ margin: 0 }}>
        <span>{label}</span>
        <input inputMode="numeric" placeholder="1001" value={no} onChange={(e) => setNo(e.target.value)} aria-label="Номер игрока" />
      </label>
      <button disabled={!clean}>Открыть</button>
    </form>
  );
}
