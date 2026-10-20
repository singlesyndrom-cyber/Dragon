/** Судьи клуба: направления и проверка, может ли человек вести турнир. */
export const JUDGE_GAMES: Record<string, string> = { mtg: "Magic", edh: "EDH", berserk: "Берсерк" };

export function judgeDirection(game: string, format: string): string {
  if (format === "edh") return "edh";
  return game === "berserk" ? "berserk" : "mtg";
}

/** membership - ответ /clubs/{id}/membership. Организатор ведёт всё, судья - свои направления. */
export function canRun(membership: any, t: { game: string; format: string }): boolean {
  if (!membership) return false;
  return !!membership.can_manage || (membership.judge_games || []).includes(judgeDirection(t.game, t.format));
}
