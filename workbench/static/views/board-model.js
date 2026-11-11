/* Pure view-model helpers: overview counts and filters without a browser dependency. */
export const categoryOf = (c) => String(c.category || "misc").toLowerCase();
export const challengeStatus = (c) => c.case?.exists ? (c.case.status || "new") : "new";
export const isDone = (c) => !!c.case?.exists && ["solved", "submitted", "closed"].includes(c.case.status);
const pointsOf = (c) => Number.isFinite(Number(c.points)) ? Number(c.points) : 0;
const categoryRank = { crypto: 0, pwn: 1, reverse: 2, web: 3, misc: 4, forensics: 5 };

export function categoriesOf(challenges) {
  return [...new Set(challenges.map(categoryOf))].sort((a, b) =>
    (categoryRank[a] ?? 9) - (categoryRank[b] ?? 9) || a.localeCompare(b));
}

export function boardSummary(challenges) {
  const done = challenges.filter(isDone);
  return {
    total: challenges.length,
    solved: done.length,
    active: challenges.filter((c) => ["in_progress", "candidate_found"].includes(challengeStatus(c))).length,
    blocked: challenges.filter((c) => challengeStatus(c) === "blocked").length,
    points: challenges.reduce((sum, c) => sum + pointsOf(c), 0),
    solvedPoints: done.reduce((sum, c) => sum + pointsOf(c), 0),
    percent: challenges.length ? Math.round(done.length / challenges.length * 100) : 0,
  };
}

export function filterChallenges(challenges, { query = "", status = "all", category = "all" } = {}) {
  const needle = String(query).trim().toLowerCase();
  return challenges.filter((c) => {
    const text = `${c.name || ""} ${c.slug || ""} ${categoryOf(c)} ${c.description || ""}`.toLowerCase();
    return (!needle || text.includes(needle))
      && (status === "all" || challengeStatus(c) === status)
      && (category === "all" || categoryOf(c) === category);
  });
}
