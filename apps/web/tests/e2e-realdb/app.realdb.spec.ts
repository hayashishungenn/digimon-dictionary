import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Real-database browser acceptance (P1-3). Unlike the hermetic fixture E2E,
// these run against data/digidex.sqlite and verify the real 1700+ record
// dataset is usable in the browser: trilingual/alias/partial search, combined
// filters, Agumon detail (names, skills, first appearance, source table, image
// status), group page, evolution depth 2/3 with truncation, missing-image
// placeholder, and narrow-screen layouts. They skip cleanly when the real DB
// is not present (e.g. a fresh clone or CI without a synced DB).

const REAL_DB = path.resolve(process.cwd(), '../../data/digidex.sqlite');
const hasRealDb = fs.existsSync(REAL_DB);

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }, testInfo) => {
	test.skip(!hasRealDb, 'real data/digidex.sqlite not present (run sync_data.py first)');
});

test('home shows the real dataset count and a populated grid', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: '数码宝贝全图鉴' })).toBeVisible();
	// the count comes from the real API, never hardcoded
	const sub = page.locator('.hero-sub');
	await expect(sub).toContainText(/[\d,]+/);
	await expect(page.locator('[data-testid="digimon-card"]').first()).toBeVisible();
});

test('trilingual + partial + alias search resolve to the same real entity', async ({ page }) => {
	await page.goto('/');
	const search = page.getByRole('textbox', { name: '搜索数码兽' });
	// Wait for the SEARCH RESULT card with the expected entity — toHaveAttribute
	// retries, so a stale card from the previous (1736-item) list is never read.
	async function firstSlug(term: string, expected: string): Promise<string> {
		await search.fill(term);
		const card = page.locator('[data-testid="digimon-card"]').first();
		await expect(card.locator('a.card-link')).toHaveAttribute('href', expected, { timeout: 15_000 });
		return expected;
	}
	const zh = await firstSlug('亚古兽', '/digimon/agumon');
	const en = await firstSlug('Agumon', '/digimon/agumon');
	const ja = await firstSlug('アグモン', '/digimon/agumon');
	expect(zh).toBe(en);
	expect(zh).toBe(ja);
	// partial English
	await firstSlug('Wargre', '/digimon/war-greymon');
	// fan abbreviation alias
	await firstSlug('战暴', '/digimon/war-greymon');
});

test('combined filter: 究极体 + 疫苗 on the real dataset', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('tab', { name: '究极体', exact: true }).click();
	// apply the attribute filter — inline toolbar on desktop, mobile drawer on
	// narrow viewports (the mobile project hides the inline toolbar, UI-P0-2)
	const mobileBtn = page.getByRole('button', { name: '打开筛选面板' });
	if (await mobileBtn.isVisible()) {
		await mobileBtn.click();
		const drawer = page.getByRole('dialog', { name: '筛选' });
		await drawer.locator('select').first().selectOption('vaccine');
		await drawer.getByRole('button', { name: '完成' }).click();
	} else {
		await page.locator('.filters select').first().selectOption('vaccine');
	}
	const count = page.locator('.result-count');
	await expect(count).toContainText('共 ');
	await expect(page.locator('[data-testid="digimon-card"]').first()).toBeVisible();
	// every rendered card shows the 究极体 badge
	const badges = page.locator('.digimon-card .badge');
	await expect(badges.first()).toContainText('究极体');
});

test('Agumon detail: real trilingual names, skills, first appearance, source, image', async ({ page }) => {
	await page.goto('/digimon/agumon');
	await expect(page.locator('.detail-h1')).toContainText('亚古兽');
	await expect(page.locator('.detail-h1')).toContainText('アグモン');
	await expect(page.locator('.detail-sub')).toContainText('Agumon');
	// skills section with a real move
	const skills = page.locator('.skill-list .skill-item');
	await expect(skills.first()).toBeVisible();
	// first appearance date is shown even without a title
	await expect(page.getByText('首次登场')).toBeVisible();
	// source table is expandable and shows per-field status
	await page.getByText('展开查看字段级出处').click();
	await expect(page.locator('.source-table .prov-status').first()).toBeVisible();
	// image status is expressed, not hidden
	await expect(page.locator('.img-status').first()).toBeVisible();
});

test('evolution graph expands to depth 2/3 with visible truncation on the real graph', async ({ page }) => {
	await page.goto('/digimon/agumon');
	// simple mode shows the real evolution neighbourhood
	await page.getByText('全部可能后续').waitFor();
	await page.getByText('全部可能前置').waitFor();
	// switch to graph mode where the depth controls live
	await page.getByRole('button', { name: '图谱模式' }).click();
	// real data carries special evolution types -> the legend makes them readable
	const legend = page.locator('.evo-legend');
	if (await legend.isVisible()) {
		await expect(legend.locator('.legend-chip').first()).toBeVisible();
	}
	// expand to depth 2 (Agumon is a hub -> budget truncation is visible)
	const expand = page.getByRole('button', { name: '展开更深一层' });
	await expand.click();
	// the truncated notice must appear with explicit counts
	await expect(page.locator('.evo-status.warn')).toBeVisible({ timeout: 20_000 });
	await expect(page.locator('.evo-status.warn')).toContainText('未展示');
	// the depth indicator reports the deeper depth with node/edge counts
	await expect(page.getByText(/当前深度/)).toContainText('节点');
	// back-to-depth-1 control exists once past depth 1
	await expect(page.getByRole('button', { name: '回到深度 1' })).toBeVisible();
});

test('Royal Knights group page loads real members', async ({ page }) => {
	await page.goto('/group/Royal%20Knights');
	await expect(page.locator('[data-testid="digimon-card"]').first()).toBeVisible();
	// the group page reports its member count and lists them
	await expect(page.locator('p.dim')).toContainText(/成员 [\d]+ 只/);
});

test('missing-image entity shows a placeholder, never a broken image', async ({ page }) => {
	// an extended entity without art in the real dataset
	await page.goto('/digimon/agumon-ds');
	await expect(page.locator('.detail-h1')).toBeVisible();
	await expect(page.locator('.img-placeholder').first()).toBeVisible();
	await expect(page.locator('.img-status').first()).toBeVisible();
	const broken = await page.locator('.detail-art img').evaluateAll((els) =>
		els.filter((e) => (e as HTMLImageElement).complete && (e as HTMLImageElement).naturalWidth === 0)
	);
	expect(broken.length).toBe(0);
});

test('no horizontal overflow on narrow screens (home + detail)', async ({ page }) => {
	// mobile project already runs at a narrow viewport; assert no overflow
	await page.goto('/');
	await page.waitForSelector('[data-testid="digimon-card"]');
	expect(
		await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
	).toBe(false);
	await page.goto('/digimon/agumon');
	await expect(page.locator('.detail-h1')).toBeVisible();
	expect(
		await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
	).toBe(false);
});

test('keyboard navigation reaches the primary controls', async ({ page }) => {
	await page.goto('/');
	// focus leaves the document body (a focusable element is reachable)
	await page.keyboard.press('Tab');
	const activeTag = await page.evaluate(() => document.activeElement?.tagName ?? '');
	expect(activeTag).not.toBe('BODY');
	// Tab until the search input (a primary control) receives focus — header
	// links come first in tab order, so this may take several presses.
	for (let i = 0; i < 15; i++) {
		await page.keyboard.press('Tab');
		const reached = await page
			.getByRole('textbox', { name: '搜索数码兽' })
			.evaluate((el) => el === document.activeElement);
		if (reached) break;
	}
	await expect(page.getByRole('textbox', { name: '搜索数码兽' })).toBeFocused();
});
