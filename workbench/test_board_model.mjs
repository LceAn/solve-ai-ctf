import test from 'node:test';
import assert from 'node:assert/strict';
import { categoryOf, categoriesOf, challengeStatus, isDone, boardSummary, filterChallenges } from './static/views/board-model.js';

const challenges = [
  { name: 'RSA Gateway', slug: 'rsa', category: 'Crypto', points: 500, description: '残缺证书', case: { exists: true, status: 'solved' } },
  { name: 'Web', slug: 'web', category: 'web', points: 100, case: { exists: true, status: 'blocked' } },
  { name: 'Pending', slug: 'pending', category: 'reverse', points: '200', case: { exists: true, status: 'candidate_found' } },
  { name: 'Running', slug: 'run', category: 'web', points: 50, case: { exists: true, status: 'in_progress' } },
  { name: 'Closed', slug: 'closed', category: 'misc', points: 40, case: { exists: true, status: 'closed' } },
  { name: 'Submitted', slug: 'submitted', category: 'ai', points: 60, case: { exists: true, status: 'submitted' } },
  { name: 'Not initialized', slug: 'new', points: null, case: { exists: false } },
];
test('summary counts blocked separately from work in progress', () => {
  assert.deepEqual(boardSummary(challenges), { total: 7, solved: 3, active: 2, blocked: 1, points: 950, solvedPoints: 600, percent: 43 });
});
test('empty competition is zero, never NaN', () => {
  assert.deepEqual(boardSummary([]), { total: 0, solved: 0, active: 0, blocked: 0, points: 0, solvedPoints: 0, percent: 0 });
});
test('non-numeric points do not poison totals', () => {
  assert.equal(boardSummary([{ points: 'invalid' }, { points: undefined }]).points, 0);
});
test('categories normalize case, deduplicate and include custom categories', () => {
  assert.deepEqual(categoriesOf(challenges), ['crypto', 'reverse', 'web', 'misc', 'ai']);
  assert.equal(categoryOf({}), 'misc');
});
test('search is case-insensitive and trims surrounding whitespace', () => {
  assert.equal(filterChallenges(challenges, { query: ' RSA ' })[0].slug, 'rsa');
});
test('search includes Chinese descriptions and slugs', () => {
  assert.equal(filterChallenges(challenges, { query: '残缺' })[0].slug, 'rsa');
  assert.equal(filterChallenges(challenges, { query: 'pending' })[0].slug, 'pending');
});
test('category, state and search filters intersect', () => {
  assert.deepEqual(filterChallenges(challenges, { category: 'web', status: 'blocked', query: 'web' }).map((c) => c.slug), ['web']);
  assert.equal(filterChallenges(challenges, { category: 'crypto', status: 'blocked' }).length, 0);
});
test('closed remains a selectable state and counts towards completion', () => {
  const closed = filterChallenges(challenges, { status: 'closed' });
  assert.equal(closed.length, 1); assert.ok(isDone(closed[0]));
});
test('missing case is pending, not completed', () => {
  assert.equal(challengeStatus({}), 'new');
  assert.equal(isDone({ case: { exists: false, status: 'solved' } }), false);
  assert.equal(filterChallenges(challenges, { status: 'new' }).length, 1);
});
test('default filters preserve all challenges without mutating the source', () => {
  const original = JSON.stringify(challenges);
  assert.deepEqual(filterChallenges(challenges), challenges);
  categoriesOf(challenges); boardSummary(challenges);
  assert.equal(JSON.stringify(challenges), original);
});
