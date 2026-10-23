"use client";

import { DECK_POLICY } from "@/lib/tournamentKinds";

export type Fields = {
  name: string; starts_at: string; description: string; rounds: string;
  deck_policy: string; self_registration: boolean; max_players: string; league_id: string; silent: boolean;
};

export const EMPTY: Fields = {
  name: "", starts_at: "", description: "", rounds: "", deck_policy: "optional",
  self_registration: true, max_players: "", league_id: "", silent: false,
};

/** Тело запроса к API из полей формы (пустое -> не задано). */
export function toBody(f: Fields, format: string) {
  const b: any = {
    name: f.name.trim(), description: f.description.trim(), deck_policy: f.deck_policy,
    self_registration: f.self_registration, max_players: f.max_players ? +f.max_players : null,
    league_id: f.league_id ? +f.league_id : null, silent: f.silent,
  };
  if (f.starts_at) b.starts_at = f.starts_at;
  if (format !== "edh" && f.rounds) b.rounds = +f.rounds;
  return b;
}

/** Поля турнира (общие для мастера создания и вкладки «Настройки»). */
export default function TournamentFields({ f, set, format, seasons }: {
  f: Fields; set: (patch: Partial<Fields>) => void; format: string; seasons: any[] | null;
}) {
  const on = (k: keyof Fields) => (e: { target: { value: string } }) => set({ [k]: e.target.value } as Partial<Fields>);
  return (
    <>
      <fieldset>
        <legend>Основное</legend>
        <label><span>Название</span><input required minLength={2} maxLength={128} value={f.name} onChange={on("name")} /></label>
        <div className="row inline">
          <label><span>Начало (московское время)</span><input type="datetime-local" value={f.starts_at} onChange={on("starts_at")} /></label>
          {format !== "edh" ? (
            <label><span>Туров</span>
              <input type="number" min={1} max={15} value={f.rounds} onChange={on("rounds")} style={{ width: 110 }}
                placeholder={format === "fast_swiss" ? "1" : "авто"} />
            </label>
          ) : null}
        </div>
        <label><span>Описание для игроков: место, взнос, призы, правила. Поддерживается Markdown</span>
          <textarea value={f.description} onChange={on("description")} maxLength={5000} style={{ minHeight: 120 }} />
        </label>
      </fieldset>

      {seasons ? (
        <fieldset>
          <legend>Сезон лиги</legend>
          {seasons.length ? (
            <div className="choice-list">
              <label className="choice"><input type="radio" name="league" checked={!f.league_id} onChange={() => set({ league_id: "" })} />
                <span>Без сезона{format === "edh" ? ": банк клуба" : ""}</span></label>
              {seasons.map((s) => (
                <label key={s.id} className="choice">
                  <input type="radio" name="league" checked={f.league_id === String(s.id)} onChange={() => set({ league_id: String(s.id) })} />
                  <span>{s.name} <span className="muted small">до {new Date(s.ends_on).toLocaleDateString("ru-RU")}{s.status === "upcoming" ? ", ещё не начался" : ""}</span></span>
                </label>
              ))}
            </div>
          ) : <p className="hint">Подходящих сезонов в клубе нет. Сезон создаётся в «Управлении клубом».</p>}
        </fieldset>
      ) : null}

      <fieldset>
        <legend>Участники и деклисты</legend>
        <div className="choice-list">
          <label className="choice"><input type="radio" name="selfreg" checked={f.self_registration} onChange={() => set({ self_registration: true })} />
            <span>Игроки записываются сами по ссылке, организатор тоже может добавлять</span></label>
          <label className="choice"><input type="radio" name="selfreg" checked={!f.self_registration} onChange={() => set({ self_registration: false })} />
            <span>Записывает только организатор (удобно для вечера на месте)</span></label>
        </div>
        <div className="row inline">
          <label><span>Лимит участников</span>
            <input type="number" min={2} max={512} value={f.max_players} onChange={on("max_players")} placeholder="без лимита" style={{ width: 150 }} />
          </label>
          <label><span>Деклисты</span>
            <select value={f.deck_policy} onChange={on("deck_policy")}>
              {Object.entries(DECK_POLICY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        {f.deck_policy === "required" ? <p className="hint">Перед стартом сайт покажет, кто не подал деклист; начать можно и без них, с подтверждением.</p> : null}
        <label className="check">
          <input type="checkbox" checked={f.silent} onChange={(e) => set({ silent: e.target.checked })} />
          <span>Тестовый турнир — без оповещений: ни анонса, ни напоминаний, ни итогов в Telegram и VK</span>
        </label>
      </fieldset>
    </>
  );
}
