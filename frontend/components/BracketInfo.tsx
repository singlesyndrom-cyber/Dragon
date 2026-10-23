import type { Assessment } from "@/lib/brackets";

/** Оценка брекета по карточкам: что нашлось и почему. Подсказка, не вердикт. */
export default function BracketInfo({ a, declared }: { a: Assessment; declared?: number | null }) {
  const over = declared != null && a.min_bracket > declared;
  return (
    <div className={`panel bracketinfo${over ? " is-bad" : ""}`}>
      <h3 style={{ margin: 0 }}>Брекет по карточкам: {a.label}{declared != null ? <span className="muted small"> · заявлен {declared}</span> : null}</h3>
      {a.reasons.length ? <ul className="small">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        : <p className="muted small" style={{ margin: "6px 0 0" }}>Game Changers, массового лишения земель, экстра-ходов и известных комбо из двух карт не найдено.
          1 или 2 — решает задумка колоды.</p>}
      {a.game_changers.length ? <p className="small" style={{ margin: "6px 0 0" }}><b>Game Changers:</b> {a.game_changers.join(", ")}</p> : null}
      {a.extra_turns.length ? <p className="small" style={{ margin: "4px 0 0" }}><b>Экстра-ходы:</b> {a.extra_turns.join(", ")}</p> : null}
      <p className="hint" style={{ margin: "6px 0 0" }}>Оценка по официальным Commander Brackets: Game Changers (список Wizards через Scryfall), массовое лишение земель,
        экстра-ходы и известные комбо из двух карт. Брекет — договорённость за столом: окончательно решают игроки и судья.</p>
    </div>
  );
}
