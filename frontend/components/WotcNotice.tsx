/** Обязательная пометка по Fan Content Policy Wizards of the Coast и указание источника данных. */
export default function WotcNotice() {
  return (
    <p className="muted small section" style={{ maxWidth: "80ch" }}>
      Данные и изображения карт Magic: The Gathering — <a href="https://scryfall.com">Scryfall</a>, цены ориентировочные.
      Dragon — неофициальный фан-контент в рамках Fan Content Policy, не одобрен и не поддерживается Wizards.
      Часть материалов принадлежит Wizards of the Coast. ©Wizards of the Coast LLC.
    </p>
  );
}
