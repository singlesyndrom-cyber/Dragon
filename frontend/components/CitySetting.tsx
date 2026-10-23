"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

/** Город игрока для рейтинга. Пусто - город клуба, где игрок сыграл больше всего турниров. */
export default function CitySetting({ playerNo }: { playerNo: number }) {
  const [city, setCity] = useState("");
  const [current, setCurrent] = useState<{ city: string | null; own: boolean } | null>(null);
  const { busy, error, done, run } = useAction();
  useEffect(() => {
    api<any>(`/ratings/player/${playerNo}`).then((r) => {
      setCurrent({ city: r.city, own: r.city_own });
      if (r.city_own) setCity(r.city || "");
    }).catch(() => {});
  }, [playerNo]);
  const save = (value: string) => run(async () => {
    const r = await api<any>("/ratings/me/city", { method: "PUT", body: { city: value } });
    setCurrent({ city: r.city, own: r.city_own });
    setCity(r.city_own ? r.city : "");
  }, "Город сохранён");
  return (
    <div className="panel" id="city">
      <h3>Город в рейтинге</h3>
      <p className="muted small">
        {current?.city ? <>Сейчас: <b>{current.city}</b>{current.own ? "" : " — по клубу, где вы чаще играете"}. </> : "Город пока не определён. "}
        По нему считается ваше место в городе и рейтинг городов. <Link href="/ratings">Рейтинг →</Link>
      </p>
      <form className="row inline" onSubmit={(e) => { e.preventDefault(); save(city); }}>
        <input value={city} onChange={(e) => setCity(e.target.value)} maxLength={64} placeholder="например, Севастополь" aria-label="Ваш город для рейтинга" />
        <button type="submit" disabled={busy}>Сохранить</button>
        {current?.own ? <button type="button" className="link-btn" disabled={busy} onClick={() => save("")}>Брать по клубу</button> : null}
      </form>
      <Status error={error} done={done} />
    </div>
  );
}
