/*
 * Демо-данные для локального просмотра сайта: игроки, клуб, турниры (швейцарка, быстрый швейцарец,
 * два EDH-ивента), колоды и новости. Всё создаётся через обычный API, как это сделали бы люди.
 *
 * Как запустить: войдите на сайт (http://localhost:3000) под администратором, откройте консоль разработчика (F12 → Console),
 * вставьте содержимое файла и нажмите Enter. Повторный запуск создаст ещё один такой же набор.
 *
 * Тестовые аккаунты: demo1@example.com … demo8@example.com, пароль у всех DEMO_PASSWORD ниже.
 * demo1 — организатор демо-клуба. Только для локальной разработки, не используйте на сервере.
 */
const DEMO_PASSWORD = "dragon-demo-2026";

const demoSeed = async () => {
  const log = [];
  const call = async (path, { token, method, body } = {}) => {
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const r = await fetch("/api" + path, {
      method: method || (body !== undefined ? "POST" : "GET"), headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await r.text();
    if (!r.ok) throw new Error(`${method || "POST"} ${path}: ${r.status} ${text.slice(0, 200)}`);
    return text ? JSON.parse(text) : null;
  };

  // --- игроки ---
  const names = ["Ярослав", "Мира", "Кузнец", "Лиса", "Арсений", "Вера", "Тимур", "Ника"];
  const users = [];
  for (let i = 0; i < names.length; i++) {
    const email = `demo${i + 1}@example.com`;
    let tok;
    try {
      tok = (await call("/auth/register", { body: { email, password: DEMO_PASSWORD, nickname: names[i] } })).access_token;
    } catch {
      tok = (await call("/auth/login", { body: { email, password: DEMO_PASSWORD } })).access_token;
    }
    const me = await call("/auth/me", { token: tok });
    users.push({ token: tok, id: me.id, name: names[i] });
  }
  const org = users[0].token;
  log.push(`игроков: ${users.length}`);

  // --- клуб ---
  const suffix = Math.random().toString(36).slice(2, 5);
  // клуб создаёт только «Создатель Клуба»: заявку организатора одобряет администратор,
  // поэтому скрипт запускают, войдя на сайт под администратором (его токен - в localStorage)
  const adminToken = localStorage.getItem("dragon_token");
  if (!adminToken) throw new Error("Войдите на сайт под администратором и запустите скрипт снова");
  const req = await call("/creator-requests", {
    token: org, body: { club_name: `Демо-клуб «Грифон» ${suffix}`, city: "Москва", about: "Демонстрационный клуб для проверки платформы." },
  });
  await call(`/admin/creator-requests/${req.id}/approve`, { token: adminToken, body: {} });
  const club = await call("/clubs", {
    token: org,
    body: {
      name: `Демо-клуб «Грифон» ${suffix}`, city: "Москва",
      description: "Демонстрационный клуб: турниры по Magic и «Берсерку» по пятницам, EDH по средам.",
    },
  });
  log.push(`клуб: ${club.slug}`);

  const iso = (daysFromNow, hour) => {
    const d = new Date(Date.now() + daysFromNow * 864e5);
    d.setHours(hour, 0, 0, 0);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(hour)}:00:00`;
  };
  const newT = (body) => call("/tournaments", { token: org, body: { club_id: club.id, ...body } });
  const register = async (tid, list, bracket = 2) => {
    for (const u of list) await call(`/tournaments/${tid}/register?bracket=${bracket}`, { token: u.token, method: "POST" });
  };

  // --- колоды (для меты и проверки деклистов) ---
  const deckTexts = [
    ["Atraxa, Praetors' Voice", "1 Sol Ring\n1 Arcane Signet\n1 Doubling Season\n1 Cultivate\n30 Forest"],
    ["Krenko, Mob Boss", "1 Sol Ring\n1 Goblin Chieftain\n1 Skirk Prospector\n1 Impact Tremors\n32 Mountain"],
    ["Edgar Markov", "1 Sol Ring\n1 Arcane Signet\n1 Cordelia Cross\n1 Bloodline Keeper\n30 Swamp"],
    ["Atraxa, Praetors' Voice", "1 Sol Ring\n1 Cultivate\n1 Smothering Tithe\n1 Rhystic Study\n30 Plains"],
    ["Kinnan, Bonder Prodigy", "1 Sol Ring\n1 Arcane Signet\n1 Rhystic Study\n1 Basalt Monolith\n30 Island"],
    ["Krenko, Mob Boss", "1 Sol Ring\n1 Impact Tremors\n1 Skirk Prospector\n1 Purphoros, God of the Forge\n30 Mountain"],
    ["Edgar Markov", "1 Sol Ring\n1 Smothering Tithe\n1 Bloodline Keeper\n1 Sorin, Imperious Bloodlord\n30 Swamp"],
    ["Kinnan, Bonder Prodigy", "1 Sol Ring\n1 Rhystic Study\n1 Cultivate\n1 Basalt Monolith\n30 Forest"],
  ];
  const decks = [];
  for (let i = 0; i < users.length; i++) {
    const [commander, text] = deckTexts[i];
    decks.push((await call("/decks", { token: users[i].token, body: { name: `Демо: ${commander}`, commander, text } })).id);
  }

  // --- 1. Швейцарка, завершена ---
  const swiss = (await newT({ name: "Пятничный модерн", game: "mtg", format: "swiss", rounds: 3, starts_at: iso(-9, 19) })).id;
  await register(swiss, users);
  await call(`/tournaments/${swiss}/start`, { token: org, method: "POST" });
  for (let rnd = 1; rnd <= 3; rnd++) {
    const pairs = await call(`/tournaments/${swiss}/round/${rnd}`);
    let k = 0;
    for (const m of pairs) {
      if (!m.p2) continue;
      const result = (rnd + k) % 5 === 0 ? "draw" : (rnd + k) % 3 === 0 ? "p2" : "p1";
      await call(`/tournaments/matches/${m.match_id}/result`, { token: org, body: { result } });
      k++;
    }
    if (rnd < 3) await call(`/tournaments/${swiss}/next-round`, { token: org, method: "POST" });
  }
  await call(`/tournaments/${swiss}/finish`, { token: org, method: "POST" });
  log.push("швейцарка завершена");

  // --- 2. Быстрый швейцарец «Берсерк», завершён ---
  const fast = (await newT({ name: "Берсерк: быстрый вечер", game: "berserk", format: "fast_swiss", starts_at: iso(-5, 18) })).id;
  await register(fast, users.slice(0, 7));
  await call(`/tournaments/${fast}/start`, { token: org, method: "POST" });
  for (const m of await call(`/tournaments/${fast}/round/1`)) {
    if (m.p2) await call(`/tournaments/matches/${m.match_id}/result`, { token: org, body: { result: m.table === 2 ? "draw" : "p1" } });
  }
  await call(`/tournaments/${fast}/finish`, { token: org, method: "POST" });
  log.push("быстрый швейцарец завершён");

  // --- 3. EDH-ивент с деклистами, завершён ---
  const edh1 = (await newT({ name: "EDH-среда #1", game: "mtg", format: "edh", starts_at: iso(-7, 19) })).id;
  for (let i = 0; i < users.length; i++) {
    await call(`/tournaments/${edh1}/register?bracket=${i < 4 ? 2 : 3}`, { token: users[i].token, method: "POST" });
    await call(`/decks/${decks[i]}/attach/${edh1}`, { token: users[i].token, method: "PUT" });
    await call(`/edh/${edh1}/players/${users[i].id}`, { token: org, method: "PUT", body: { checked_in: true } });
  }
  for (let round = 0; round < 2; round++) {
    await call(`/edh/${edh1}/round`, { token: org, method: "POST" });
    const tables = await call(`/edh/${edh1}/tables`);
    for (const [i, t] of tables.entries()) {
      if ((i + round) % 3 === 2) await call(`/edh/tables/${t.table_id}/draw`, { token: org, method: "POST" });
      else await call(`/edh/tables/${t.table_id}/win`, { token: org, body: { winner_id: t.seats[(i + round) % t.seats.length].user_id } });
    }
  }
  await call(`/edh/${edh1}/finish`, { token: org, method: "POST" });
  log.push("EDH #1 завершён");

  // --- 4. EDH-ивент идёт прямо сейчас ---
  const edh2 = (await newT({ name: "EDH-среда #2", game: "mtg", format: "edh", starts_at: iso(0, 19) })).id;
  for (let i = 0; i < users.length; i++) {
    await call(`/tournaments/${edh2}/register?bracket=${i < 4 ? 2 : 3}`, { token: users[i].token, method: "POST" });
    await call(`/edh/${edh2}/players/${users[i].id}`, { token: org, method: "PUT", body: { checked_in: true } });
  }
  await call(`/edh/${edh2}/round`, { token: org, method: "POST" });
  const live = await call(`/edh/${edh2}/tables`);
  await call(`/edh/tables/${live[0].table_id}/win`, { token: org, body: { winner_id: live[0].seats[1].user_id } });
  log.push("EDH #2 идёт");

  // --- 5. Анонс с открытой регистрацией ---
  const cup = (await newT({ name: "Кубок Грифона", game: "mtg", format: "swiss", starts_at: iso(3, 12) })).id;
  await register(cup, users.slice(0, 5));
  log.push("анонс кубка");

  // --- новости и комментарии ---
  const articles = [
    {
      title: "Итоги «Пятничного модерна»",
      summary: "Три тура, восемь игроков и одна ничья в решающем матче.",
      body_md: "## Как это было\n\nВосемь игроков, **три тура** по швейцарской системе. Таблица и пары — на странице турнира.\n\n- Лучший результат вечера: 3 победы из 3\n- Самый долгий матч: 52 минуты\n\nСпасибо всем, кто пришёл!",
      tags: ["модерн", "итоги"],
    },
    {
      title: "EDH по средам: как устроен банк",
      summary: "Почему победитель забирает 7% у каждого соперника и что будет, если время вышло.",
      body_md: "У каждого игрока клуба есть **банк**: на старте 1000 очков, каждую неделю +150 за приход на ивент.\n\n1. Победа до конца таймера — 7% банка каждого соперника переходят победителю.\n2. Если за 70 минут победителя нет, каждый теряет 7% своего банка.\n\nРассадка случайная внутри брекетов: сильные колоды не встречаются со слабыми.",
      tags: ["EDH", "правила"],
    },
    {
      title: "Открыта запись на «Кубок Грифона»",
      summary: "Пять туров, призы для топ-3. Деклисты принимаем до начала турнира.",
      body_md: "Запись открыта на странице турнира. Не забудьте **подать деклист** до старта — после начала изменить его нельзя.",
      tags: ["анонс"],
    },
  ];
  let firstSlug = null;
  for (const a of articles) {
    const r = await call("/news", { token: org, body: { ...a, club_id: club.id, publish: true } });
    firstSlug = firstSlug || r.slug;
  }
  await call(`/news/${encodeURIComponent(firstSlug)}/comments`, { token: users[2].token, body: { body: "Отличный вечер, жду следующую пятницу!" } });
  await call(`/news/${encodeURIComponent(firstSlug)}/comments`, { token: users[5].token, body: { body: "Ничья в третьем туре была эпичной." } });
  log.push("новости: 3");

  return { club: `/clubs/${club.slug}`, swiss, fast, edh1, edh2, cup, log };
};

typeof window !== "undefined" && (window.demoSeed = demoSeed);
demoSeed().then((r) => console.log("Демо-данные готовы", r), (e) => console.error(e));
