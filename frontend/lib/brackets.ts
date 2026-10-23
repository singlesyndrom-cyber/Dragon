/** Commander Brackets (Wizards of the Coast): названия и кратко - что разрешено. */
export const BRACKETS: [number, string, string][] = [
  [1, "Exhibition", "Тематические «показательные» колоды, победа не главное. Без Game Changers, MLD, экстра-ходов и комбо из двух карт."],
  [2, "Core", "Уровень обычной готовой колоды. Без Game Changers, MLD и комбо из двух карт; экстра-ходы — немного и без цепочек."],
  [3, "Upgraded", "Усиленная колода. До трёх Game Changers, без MLD; комбо из двух карт — не в ранней игре; экстра-ходы — немного."],
  [4, "Optimized", "Самая сильная ваша колода: ограничений, кроме бан-листа, нет."],
  [5, "cEDH", "Соревновательный EDH под мету турниров."],
];

export type Assessment = { min_bracket: number; label: string; game_changers: string[]; mld: string[];
  extra_turns: string[]; combos: string[][]; reasons: string[] };
