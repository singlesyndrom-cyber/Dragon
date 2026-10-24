import Link from "next/link";

export const metadata = {
  title: "О проекте: данные и разработка",
  description: "Откуда берутся данные о картах, как считается статистика, кто делает сайт и где найти материалы.",
};

const SECTIONS: [string, string][] = [
  ["sources", "Источники данных"], ["stats", "Статистика и приватность"], ["dev", "Разработка"],
  ["docs", "Материалы"], ["legal", "Права и контакты"],
];

export default function About() {
  return (
    <div className="home about">
      <section className="stack">
        <span className="h-kicker">О проекте</span>
        <h1>Данные, разработка и ресурсы</h1>
        <p className="lead">dragonclub.games — платформа клубов настольных ККИ: турниры, колоды, мета и рейтинги. Здесь собрано,
          откуда берутся данные о картах, как считается статистика, кто делает сайт и где найти материалы.</p>
        <nav aria-label="Разделы страницы" className="row">
          {SECTIONS.map(([id, l]) => <a key={id} href={`#${id}`} className="btn">{l}</a>)}
        </nav>
      </section>

      <section id="sources">
        <h2>Источники данных о картах</h2>
        <div className="h-two">
          <div className="h-card">
            <span className="h-label">Magic: The Gathering</span>
            <h3>Scryfall</h3>
            <p>Описания карт, издания и изображения загружаются из открытой базы Scryfall и регулярно обновляются.
              Картинки показываются через наш сервер с кэшем, чтобы не нагружать источник.</p>
            <p className="muted small">Magic: The Gathering и изображения карт принадлежат Wizards of the Coast.
              Сайт не связан с Wizards of the Coast и не одобрен ею.</p>
            <a href="https://scryfall.com" target="_blank" rel="noopener">scryfall.com →</a>
          </div>
          <div className="h-card">
            <span className="h-label">«Берсерк»</span>
            <h3>ProBerserk.ru и «Мир Хобби»</h3>
            <p>Описания карт и изданий взяты с ProBerserk.ru с указанием источника. База обновляется бережно: одна страница
              издания за раз, с паузами между запросами. Изображения карт используются с разрешения правообладателя.</p>
            <p className="muted small">Данные: ProBerserk.ru; права на игру и изображения — «Мир Хобби».</p>
            <a href="https://proberserk.ru" target="_blank" rel="noopener">proberserk.ru →</a>
          </div>
          <div className="h-card">
            <span className="h-label">«Респонс»</span>
            <h3>API «Респонса»</h3>
            <p>Карты, разъяснения правил и изображения загружаются из API разработчика игры по ключу, с разрешения правообладателя.
              Правила колод и драфта — по официальным правилам игры.</p>
            <a href="https://response-game.ru/rules" target="_blank" rel="noopener">Правила «Респонса» →</a>
          </div>
          <div className="h-card">
            <h3>Правила и форматы</h3>
            <p className="muted">Проверка колод, отряды и драфт построены по официальным расширенным и турнирным правилам
              «Берсерка» и турнирным правилам Magic: The Gathering.</p>
          </div>
          <div className="h-card">
            <h3>Файлы колод</h3>
            <p className="muted">Импорт текстовых списков MTG (Moxfield, Archidekt, Arena, MTGO), файлов NXT и .brsc для «Берсерка» —
              колоды переносятся из конструкторов без перепечатки.</p>
          </div>
        </div>
      </section>

      <section id="stats">
        <h2>Статистика и приватность</h2>
        <ul className="h-features">
          <li><b>Только клубные турниры</b><span className="muted small">Мета и винрейты считаются по турнирам, сыгранным на сайте. Внешние базы в статистику не подмешиваются.</span></li>
          <li><b>Раздельно по играм</b><span className="muted small">Magic и «Берсерк» считаются отдельно, по форматам и архетипам.</span></li>
          <li><b>Издателям — сводные данные</b><span className="muted small">Издатели видят агрегированную статистику по архетипам и картам, без личных данных игроков.</span></li>
          <li><b>Ваши данные</b><span className="muted small">Профиль, колоды и история турниров — в <Link href="/me">личном кабинете</Link>. Колоду в общую мету добавляете только вы.</span></li>
        </ul>
      </section>

      <section id="dev" className="h-band">
        <div className="h-band-text">
          <span className="h-kicker">Разработка</span>
          <h2>Сделано игроками для клубов</h2>
          <p>Проект ведёт клуб «Дракон». Разработано вместе с Claude — ИИ-ассистентом от Anthropic.</p>
          <p className="muted small">Нашли ошибку или есть идея? Напишите нам — новые функции появляются по запросам организаторов и игроков.</p>
        </div>
        <ul className="h-features">
          <li><span className="muted small">Сервер</span><b>FastAPI · PostgreSQL</b></li>
          <li><span className="muted small">Сайт</span><b>Next.js</b></li>
          <li><span className="muted small">Уведомления</span><b>Telegram · ВКонтакте · почта</b></li>
          <li><span className="muted small">Карты</span><b>Scryfall · ProBerserk.ru</b></li>
        </ul>
      </section>

      <section id="docs">
        <h2>Материалы</h2>
        <ul className="h-clubs">
          <li><a className="h-card" href="/guides/dragon-mtg.pdf" target="_blank" rel="noopener"><span className="muted small">PDF · для игроков</span><b>Путеводитель MTG</b><span className="small">Открыть →</span></a></li>
          <li><a className="h-card" href="/guides/dragon-berserk.pdf" target="_blank" rel="noopener"><span className="muted small">PDF · для игроков</span><b>Путеводитель «Берсерк»</b><span className="small">Открыть →</span></a></li>
          <li><a className="h-card" href="/guides/dragon-publisher.pdf" target="_blank" rel="noopener"><span className="muted small">PDF · для издателей</span><b>Кабинет издателя</b><span className="small">Открыть →</span></a></li>
          <li><Link className="h-card" href="/clubs/new"><span className="muted small">Для организаторов</span><b>Как открыть клуб</b><span className="small">Подать заявку →</span></Link></li>
        </ul>
      </section>

      <section id="legal" className="h-two">
        <div className="h-card">
          <h2>Права</h2>
          <p className="muted small">Названия игр, карты и изображения принадлежат их правообладателям. dragonclub.games — независимый
            клубный ресурс и не является официальным сайтом издателей. Правообладатели могут написать нам по любому вопросу об использовании материалов.</p>
        </div>
        <div className="h-card">
          <h2>Контакты</h2>
          <p className="muted small">Для игроков, клубов, издателей и правообладателей — через клуб «Дракон».</p>
          <Link href="/clubs">Клубы и их контакты →</Link>
        </div>
      </section>
    </div>
  );
}
