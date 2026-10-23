/** Замечания по формату от сервера: ошибки (не пройдёт проверку) и предупреждения. */
export default function Problems({ problems }: { problems?: { level: string; text: string }[] }) {
  if (!problems?.length) return null;
  const errors = problems.filter((p) => p.level === "error");
  return (
    <div className={`panel deckproblems ${errors.length ? "is-bad" : ""}`} role="status">
      <b>{errors.length ? "Колода не соответствует формату" : "Обратите внимание"}</b>
      <ul>{problems.map((p) => <li key={p.text} className={p.level === "error" ? "" : "muted"}>{p.text}</li>)}</ul>
    </div>
  );
}
