import { test, expect } from '@playwright/test';

// Product-spec §62 E2E scenarios: search across three languages hits the same
// entity; detail page shows trilingual names; skills; evolution navigation;
// combined filtering; favorites survive reload.
//
// Hermetic (T6.7): these run against a deterministic fixture DB built by
// tests/fixtures/build_e2e_fixture.py — no real sync, no network, no random data.

test.describe.configure({ mode: 'serial' });

test('home page loads with the digimon grid', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: '数码宝贝全图鉴' })).toBeVisible();
	await expect(page.locator('[data-testid="digimon-card"]').first()).toBeVisible();
});

test('search 亚古兽 finds Agumon and opens the same entity as アグモン / Agumon', async ({ page }) => {
	await page.goto('/');
	const search = page.getByRole('textbox', { name: '搜索数码兽' });

	// search in all three languages and assert the FIRST result resolves to the
	// same canonical entity (spec §62: same entity across languages)
	async function firstSlug(term: string): Promise<string> {
		await search.fill(term);
		const card = page.locator('[data-testid="digimon-card"]').first();
		await expect(card).toBeVisible();
		const href = await card.locator('a.card-link').getAttribute('href');
		return href ?? '';
	}

	const zhSlug = await firstSlug('亚古兽');
	const enSlug = await firstSlug('Agumon');
	const jaSlug = await firstSlug('アグモン');
	expect(zhSlug).toBeTruthy();
	expect(zhSlug).toBe(enSlug);
	expect(zhSlug).toBe(jaSlug);

	// the canonical base Agumon entity must carry all three names on detail
	await page.goto(zhSlug);
	await expect(page.locator('.detail-h1')).toContainText('亚古兽');
	await expect(page.locator('.detail-sub')).toContainText('Agumon');
});

test('detail page shows trilingual names and skills', async ({ page }) => {
	await page.goto('/digimon/agumon');
	await expect(page.locator('.detail-h1')).toContainText('亚古兽');
	await expect(page.locator('.detail-h1')).toContainText('アグモン');
	await expect(page.locator('.detail-sub')).toContainText('Agumon');
	// skills section present (may be empty for some)
	const section = page.getByText('必杀技 / 技能 Skills');
	await expect(section).toBeVisible();
});

test('clicking a next evolution opens its detail page', async ({ page }) => {
	await page.goto('/digimon/agumon');
	const nextSection = page.getByText('全部可能后续');
	await nextSection.waitFor();
	// click the first evolution node link
	const node = page.locator('.evo-row-wrap .evo-node').first();
	await node.click();
	await page.waitForURL(/\/digimon\//);
	await expect(page.locator('.detail-h1')).toBeVisible();
});

test('combined filter: 究极体 + 疫苗', async ({ page }) => {
	await page.goto('/');
	// level tab: 究极体
	await page.getByRole('tab', { name: '究极体' }).click();
	// attribute filter
	await page.locator('select').first().selectOption('vaccine');
	await expect(page.locator('[data-testid="digimon-card"]').first()).toBeVisible();
	const count = await page.locator('.result-count').textContent();
	expect(count).toContain('共');
	// every card should show 究极体
	const badges = page.locator('.digimon-card .badge');
	await expect(badges.first()).toContainText('究极体');
});

test('favorites persist across reload', async ({ page }) => {
	await page.goto('/digimon/agumon');
	const favBtn = page.locator('.detail-art .fav');
	await favBtn.click();
	await expect(favBtn).toContainText('★');
	await page.reload();
	await expect(page.locator('.detail-art .fav')).toContainText('★');
});

test('missing image shows placeholder, not broken image', async ({ page }) => {
	// agumon-ds is a digimons_net-only entity with no image in this dataset.
	await page.goto('/digimon/agumon-ds');
	// the placeholder replaces the missing image instead of a broken-image icon
	await expect(page.locator('.img-placeholder').first()).toBeVisible();
	// and the main art area has no broken <img>
	const artImgs = page.locator('.detail-art img');
	const broken = await artImgs.evaluateAll((els) =>
		els.filter((e) => (e as HTMLImageElement).complete && (e as HTMLImageElement).naturalWidth === 0)
	);
	expect(broken.length).toBe(0);
});

test('empty state shows friendly message', async ({ page }) => {
	await page.goto('/');
	// a filter with no matches must show the empty-state message, not crash
	await page.getByRole('tab', { name: '数码蛋' }).click();
	await expect(page.locator('.result-count')).toContainText('共 0 只');
	await expect(page.getByText('没有找到匹配的数码兽')).toBeVisible();
});

test('official / extended toggle filters the grid', async ({ page }) => {
	await page.goto('/');
	await page.waitForSelector('[data-testid="digimon-card"]');
	const countAll = await page.locator('.result-count').textContent();
	await page.getByRole('button', { name: '官方图鉴' }).click();
	await expect(page.locator('.result-count')).not.toHaveText(countAll ?? '');
	const countOfficial = await page.locator('.result-count').textContent();
	await page.getByRole('button', { name: '扩展图鉴' }).click();
	await expect(page.locator('.result-count')).not.toHaveText(countOfficial ?? '');
	const countExtended = await page.locator('.result-count').textContent();
	// official-only and extended-only each are subsets of the full set
	const nAll = parseInt(countAll?.match(/\d+/)?.at(0) ?? '0');
	const nOff = parseInt(countOfficial?.match(/\d+/)?.at(0) ?? '0');
	const nExt = parseInt(countExtended?.match(/\d+/)?.at(0) ?? '0');
	expect(nOff).toBeGreaterThan(0);
	expect(nExt).toBeGreaterThan(0);
	expect(nOff + nExt).toBe(nAll);
});

test('about page shows runtime snapshot counts', async ({ page }) => {
	await page.goto('/about');
	await expect(page.getByText('数据集快照 Dataset Snapshot')).toBeVisible();
	// counts come from the live API, never hardcoded
	await expect(page.locator('.stat-v').first()).toBeVisible();
	const official = page.locator('.stat-cell').nth(0).locator('.stat-v');
	const total = page.locator('.stat-cell').nth(2).locator('.stat-v');
	await expect(official).not.toHaveText('0');
	await expect(total).not.toHaveText('0');
});

test('search 战暴 (fan abbreviation) resolves to WarGreymon', async ({ page }) => {
	// §35: fan shorthand must resolve via fan_translation aliases
	await page.goto('/');
	await page.getByRole('textbox', { name: '搜索数码兽' }).fill('战暴');
	const card = page.locator('[data-testid="digimon-card"]').first();
	await expect(card).toBeVisible();
	const href = await card.locator('a.card-link').getAttribute('href');
	expect(href).toBe('/digimon/war-greymon');
});

test('detail page shows representative primary evolution line', async ({ page }) => {
	// Agumon has Wikimon primary-line edges (Koromon → Agumon → Greymon ...)
	await page.goto('/digimon/agumon');
	await page.getByText('代表进化路线（主线）').waitFor();
	// the primary chain is a horizontal chain containing the current digimon
	await expect(page.locator('.evo-chain')).toContainText('Agumon');
});

test('narrow screen has no horizontal overflow', async ({ page }) => {
	// 390×844 (iPhone 12-class) — the layout must not overflow horizontally.
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/');
	await page.waitForSelector('[data-testid="digimon-card"]');
	const homeOverflow = await page.evaluate(
		() => document.documentElement.scrollWidth > document.documentElement.clientWidth
	);
	expect(homeOverflow).toBe(false);

	await page.goto('/digimon/agumon');
	await expect(page.locator('.detail-h1')).toBeVisible();
	const detailOverflow = await page.evaluate(
		() => document.documentElement.scrollWidth > document.documentElement.clientWidth
	);
	expect(detailOverflow).toBe(false);
});
