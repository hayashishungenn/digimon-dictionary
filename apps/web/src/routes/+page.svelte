<script lang="ts">
	import { api, debounce, type ListFilters } from '$lib/api/client';
	import type { DigimonListItem } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';
	import FilterControls from '$lib/components/FilterControls.svelte';
	import { ensureMeta, metaState } from '$lib/stores/meta.svelte';

	import { onMount } from 'svelte';

	let items = $state<DigimonListItem[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let q = $state('');
	let level = $state<string | null>(null);
	let attribute = $state<string | null>(null);
	let typeName = $state<string | null>(null);
	let field = $state<string | null>(null);
	let group = $state<string | null>(null);
	let xAb = $state<boolean | null>(null);
	let official = $state<'all' | 'official' | 'extended'>('all');
	let sort = $state('name');
	let offset = $state(0);
	const PAGE = 60;

	// A request sequence token: only the newest request may update state, so a
	// slow stale response can never overwrite a newer search/list result (T6.1).
	let reqSeq = 0;

	// level tabs come from the API meta (never hardcoded, so a new level enum
	// value shows up without a code change — UI-P0-1/UI-P0-2).
	let levelTabs = $derived([
		{ value: null as string | null, label: '全部' },
		...(metaState.meta?.levels ?? []).map((l) => ({ value: l.value, label: l.label_zh })),
	]);

	// mobile filter drawer (UI-P0-2): desktop shows the toolbar inline; on
	// narrow screens a 筛选 button opens a bottom sheet with the same controls.
	let showFilters = $state(false);

	// current active conditions as removable chips + a clear-all entry
	type ActiveFilter = { key: string; label: string };
	const SORT_LABELS: Record<string, string> = {
		name: '名称',
		id: 'ID',
		debut: '首次登场',
		recent: '最近更新',
		level: '等级'
	};
	let activeFilters = $derived.by(() => {
		const out: ActiveFilter[] = [];
		const meta = metaState.meta;
		if (level) {
			const lv = meta?.levels.find((l) => l.value === level);
			out.push({ key: 'level', label: `等级：${lv?.label_zh ?? level}` });
		}
		if (attribute) {
			const at = meta?.attributes.find((a) => a.value === attribute);
			out.push({ key: 'attribute', label: `属性：${at?.label_zh ?? attribute}` });
		}
		if (typeName) out.push({ key: 'type', label: `类型：${typeName}` });
		if (field) out.push({ key: 'field', label: `领域：${field}` });
		if (group) {
			const g = meta?.groups.find((x) => x.name === group);
			out.push({ key: 'group', label: `组织：${g?.name_zh ?? group}` });
		}
		if (xAb !== null) out.push({ key: 'xAb', label: xAb ? 'X抗体：是' : 'X抗体：否' });
		if (official !== 'all') out.push({ key: 'official', label: official === 'official' ? '官方图鉴' : '扩展图鉴' });
		if (sort !== 'name') out.push({ key: 'sort', label: `排序：${SORT_LABELS[sort] ?? sort}` });
		return out;
	});

	function clearFilter(key: string) {
		if (key === 'level') level = null;
		else if (key === 'attribute') attribute = null;
		else if (key === 'type') typeName = null;
		else if (key === 'field') field = null;
		else if (key === 'group') group = null;
		else if (key === 'xAb') xAb = null;
		else if (key === 'official') official = 'all';
		else if (key === 'sort') sort = 'name';
	}

	function clearSearch() {
		q = '';
		searchMode = false;
		// the reload effect reloads the full list and clears the URL
	}

	async function load() {
		const my = ++reqSeq;
		loading = true;
		error = null;
		try {
			const res = await api.list({
				level,
				attribute,
				type: typeName,
				field,
				group,
				x_antibody: xAb,
				official,
				sort,
				limit: PAGE,
				offset
			} satisfies ListFilters);
			if (my !== reqSeq) return; // stale response — drop it
			items = res.items;
			total = res.total;
		} catch (e) {
			if (my !== reqSeq) return;
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			if (my === reqSeq) loading = false;
		}
	}

	// search mode: switch to search results
	let searchMode = $state(false);
	const doSearch = debounce(async (term: string) => {
		const my = ++reqSeq;
		if (!term.trim()) {
			searchMode = false;
			return; // the reload effect reloads + writes the URL
		}
		searchMode = true;
		loading = true;
		error = null;
		try {
			const res = await api.search(term, 60);
			if (my !== reqSeq) return; // stale search — drop it
			items = res.items;
			total = res.count;
		} catch (e) {
			if (my !== reqSeq) return;
			error = e instanceof Error ? e.message : '搜索失败';
		} finally {
			if (my === reqSeq) loading = false;
		}
		writeUrl();
	}, 250);

	function onSearchInput(v: string) {
		q = v;
		doSearch(v);
	}

	function resetFilters() {
		level = null;
		attribute = null;
		typeName = null;
		field = null;
		group = null;
		xAb = null;
		official = 'all';
		sort = 'name';
		offset = 0;
	}

	// S1-3: filter state is persisted in the URL (?level=…&attribute=…&q=…) so a
	// refresh or a shared link restores the exact list. One-way: read once on
	// mount, write on change (replaceState — no history spam, no loop).
	function filtersToParams(): URLSearchParams {
		const sp = new URLSearchParams();
		if (level) sp.set('level', level);
		if (attribute) sp.set('attribute', attribute);
		if (typeName) sp.set('type', typeName);
		if (field) sp.set('field', field);
		if (group) sp.set('group', group);
		if (xAb !== null) sp.set('x_antibody', String(xAb));
		if (official !== 'all') sp.set('official', official);
		if (sort !== 'name') sp.set('sort', sort);
		if (q) sp.set('q', q);
		return sp;
	}

	function writeUrl() {
		const qs = filtersToParams().toString();
		const next = qs ? `?${qs}` : window.location.pathname;
		if (window.location.search !== (qs ? `?${qs}` : '')) {
			history.replaceState(null, '', next);
		}
	}

	function applyParams(sp: URLSearchParams) {
		level = sp.get('level');
		attribute = sp.get('attribute');
		typeName = sp.get('type');
		field = sp.get('field');
		group = sp.get('group');
		const xa = sp.get('x_antibody');
		xAb = xa === null ? null : xa === 'true';
		const off = sp.get('official');
		if (off === 'official' || off === 'extended') official = off;
		const st = sp.get('sort');
		if (st) sort = st;
		const qq = sp.get('q');
		q = qq ?? '';
	}

	// Filter signature — resets pagination when filters change (not on offset).
	let filterKey = $derived.by(() =>
		[level, attribute, typeName, field, group, xAb, official, sort, searchMode].join('~')
	);
	let lastKey: string | null = null;
	$effect(() => {
		if (lastKey !== null && filterKey !== lastKey) {
			offset = 0;
		}
		lastKey = filterKey;
	});

	// Reload on any reactive change (filters or pagination), and keep the URL in
	// sync (S1-3). `ready` defers the first load until onMount has applied any
	// URL params, so a deep link never shows a flicker of the unfiltered list.
	let ready = $state(false);
	$effect(() => {
		if (!ready || searchMode) return;
		load();
		writeUrl();
	});

	onMount(() => {
		ensureMeta();
		applyParams(new URLSearchParams(window.location.search));
		if (q) {
			searchMode = true;
			doSearch(q);
		}
		ready = true;
	});
</script>

<svelte:head>
	<title>DigiDex · 数码宝贝全图鉴</title>
</svelte:head>

{#if error && !loading}
	<div class="error-box" role="alert">
		无法连接数据服务：{error}。请确认后端已启动并已运行
		<code>uv run python scripts/sync_data.py</code>。
	</div>
{/if}

<div class="hero">
	<h1 class="hero-title">数码宝贝全图鉴</h1>
	<p class="hero-sub">
		三语言 Canonical 数据库 · {metaState.meta?.counts.total ?? '—'} 只收录
		{#if metaState.meta}
			<span class="faint">（官方 {metaState.meta.counts.official} · 扩展 {metaState.meta.counts.extended}）</span>
		{/if}
	</p>

	<div class="search-wrap">
		<input
			class="input search-input"
			placeholder="搜索：亚古兽 / Agumon / アグモン / 战暴 / War Greymon…"
			value={q}
			oninput={(e) => onSearchInput((e.target as HTMLInputElement).value)}
			aria-label="搜索数码兽"
		/>
		{#if q}
			<button class="search-clear" aria-label="清除搜索" onclick={clearSearch}>×</button>
		{/if}
	</div>
	{#if searchMode}
		<span class="search-mode" role="status">搜索模式</span>
	{/if}

	<button
		class="btn btn-filter-mobile"
		aria-label="打开筛选面板"
		aria-haspopup="dialog"
		onclick={() => (showFilters = true)}
	>
		筛选{activeFilters.length > 0 ? `（${activeFilters.length}）` : ''}
	</button>

	<div class="official-toggle" role="group" aria-label="图鉴范围">
		{#each [
			{ v: 'all', l: '全部' },
			{ v: 'official', l: '官方图鉴' },
			{ v: 'extended', l: '扩展图鉴' }
		] as opt}
			<button
				class="btn {official === opt.v ? 'active' : ''}"
				onclick={() => {
					official = opt.v as typeof official;
					searchMode = false;
					q = '';
				}}>{opt.l}</button>
		{/each}
	</div>

	<div class="chips level-tabs" role="tablist" aria-label="等级筛选">
		{#each levelTabs as tab}
			<button
				class="chip {level === tab.value ? 'active' : ''}"
				role="tab"
				aria-selected={level === tab.value}
				onclick={() => {
					level = tab.value;
					searchMode = false;
				}}>{tab.label}</button>
		{/each}
	</div>
</div>

{#if !searchMode}
	<div class="filters" aria-label="筛选器">
		<FilterControls bind:attribute bind:typeName bind:field bind:group bind:xAb bind:sort />
		<button class="btn" onclick={resetFilters}>重置筛选</button>
	</div>
{/if}

{#if activeFilters.length > 0 && !searchMode}
	<div class="active-filters" aria-label="当前筛选条件">
		<span class="af-label mono">当前筛选</span>
		{#each activeFilters as af}
			<button class="af-chip" onclick={() => clearFilter(af.key)} title={`清除 ${af.label}`}>{af.label} <span class="af-x" aria-hidden="true">×</span></button>
		{/each}
		<button class="af-clear" onclick={resetFilters}>清除全部</button>
	</div>
{/if}

{#if showFilters}
	<div class="drawer-overlay" onclick={() => (showFilters = false)} aria-hidden="true"></div>
	<div class="filter-drawer" role="dialog" aria-modal="true" aria-label="筛选">
		<div class="drawer-head">
			<span class="mono">筛选 FILTERS</span>
			<button class="btn" onclick={() => (showFilters = false)}>完成</button>
		</div>
		<div class="drawer-body">
			<FilterControls bind:attribute bind:typeName bind:field bind:group bind:xAb bind:sort />
			<button class="btn" onclick={resetFilters}>重置筛选</button>
		</div>
	</div>
{/if}

<div class="result-count mono">
	共 {total} 只
	{#if searchMode && q}<span class="faint">（搜索 “{q}”）</span>{/if}
</div>

{#if loading && items.length === 0}
	<div class="spinner" aria-label="加载中"></div>
{:else if items.length === 0}
	<div class="no-data">没有找到匹配的数码兽。</div>
{:else}
	<div class="grid">
		{#each items as item}
			<DigimonCard {item} />
		{/each}
	</div>

	{#if !searchMode && total > PAGE}
		<div class="pager">
			<button class="btn" disabled={offset === 0} onclick={() => (offset = Math.max(0, offset - PAGE))}>← 上一页</button>
			<span class="mono faint">
				{Math.floor(offset / PAGE) + 1} / {Math.ceil(total / PAGE)}
			</span>
			<button class="btn" disabled={offset + PAGE >= total} onclick={() => (offset += PAGE)}>下一页 →</button>
		</div>
	{/if}
{/if}

<style>
	.hero {
		padding: 26px 0 8px;
	}
	.hero-title {
		font-size: 28px;
		margin: 0;
		letter-spacing: 1px;
	}
	.hero-sub {
		color: var(--text-dim);
		margin: 4px 0 18px;
		font-size: 14px;
	}
	.search-wrap {
		position: relative;
		max-width: 640px;
	}
	.search-input {
		width: 100%;
		font-size: 16px;
		padding: 12px 16px;
		padding-right: 64px;
		border-radius: var(--radius);
	}
	.search-clear {
		position: absolute;
		right: 12px;
		top: 50%;
		transform: translateY(-50%);
		width: 28px;
		height: 28px;
		display: grid;
		place-items: center;
		border: none;
		border-radius: 50%;
		background: var(--surface-2);
		color: var(--text-dim);
		font-size: 18px;
		line-height: 1;
		transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
	}
	.search-clear:hover {
		color: var(--accent);
		background: var(--surface-3);
	}
	.search-mode {
		display: inline-block;
		margin: 6px 0 0 2px;
		font-family: var(--mono);
		font-size: 11px;
		color: var(--accent);
		background: var(--accent-soft);
		padding: 2px 8px;
		border-radius: 999px;
	}
	.official-toggle {
		display: flex;
		gap: 8px;
		margin: 14px 0;
	}
	.level-tabs {
		margin-bottom: 4px;
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: flex-end;
		margin: 10px 0 16px;
		padding: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}
	.result-count {
		margin: 14px 0 10px;
		color: var(--text-dim);
		font-size: 13px;
	}

	/* mobile filter entry — hidden on desktop, shown under 768px */
	.btn-filter-mobile {
		display: none;
		margin: 10px 0 6px;
	}

	/* active filter conditions as removable chips (UI-P0-2) */
	.active-filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin: 8px 0 4px;
	}
	.af-label {
		font-size: 11px;
		letter-spacing: 1px;
		color: var(--text-faint);
		margin-right: 2px;
	}
	.af-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border: 1px solid var(--border-strong);
		background: var(--surface-2);
		color: var(--text-dim);
		border-radius: 999px;
		padding: 3px 8px 3px 10px;
		font-size: 12px;
		transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
	}
	.af-chip:hover {
		border-color: var(--warning);
		color: var(--warning);
	}
	.af-x {
		font-family: var(--mono);
		font-size: 13px;
		line-height: 1;
	}
	.af-clear {
		border: none;
		background: none;
		color: var(--text-faint);
		font-size: 12px;
		text-decoration: underline;
		text-underline-offset: 3px;
		padding: 3px 6px;
	}
	.af-clear:hover {
		color: var(--danger);
	}

	/* mobile filter bottom-sheet (UI-P0-2) */
	.drawer-overlay {
		position: fixed;
		inset: 0;
		z-index: 90;
		background: rgba(5, 8, 16, 0.6);
		backdrop-filter: blur(2px);
	}
	.filter-drawer {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 95;
		max-height: 82vh;
		overflow-y: auto;
		background: var(--surface);
		border-top: 1px solid var(--border-strong);
		border-radius: var(--radius-lg) var(--radius-lg) 0 0;
		padding: 0 18px 20px;
		box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.5);
	}
	.drawer-head {
		position: sticky;
		top: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 0 10px;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
		margin-bottom: 12px;
		font-size: 12px;
		letter-spacing: 2px;
		color: var(--text-faint);
	}
	.drawer-body {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	@media (max-width: 767px) {
		.filters {
			display: none;
		}
		.btn-filter-mobile {
			display: inline-flex;
		}
	}
</style>
