<script lang="ts">
	import { onMount } from 'svelte';
	import { api, debounce, type ListFilters } from '$lib/api/client';
	import type { Meta, DigimonListItem } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';

	let meta = $state<Meta | null>(null);
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

	const LEVEL_TABS: Array<{ value: string | null; label: string }> = [
		{ value: null, label: '全部' },
		{ value: 'digi_egg', label: '数码蛋' },
		{ value: 'baby_i', label: '幼年期Ⅰ' },
		{ value: 'baby_ii', label: '幼年期Ⅱ' },
		{ value: 'child', label: '成长期' },
		{ value: 'adult', label: '成熟期' },
		{ value: 'perfect', label: '完全体' },
		{ value: 'ultimate', label: '究极体' },
		{ value: 'armor', label: '装甲体' },
		{ value: 'hybrid', label: '混合体' }
	];

	async function load() {
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
			items = res.items;
			total = res.total;
		} catch (e) {
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			loading = false;
		}
	}

	// search mode: switch to search results
	let searchMode = $state(false);
	const doSearch = debounce(async (term: string) => {
		if (!term.trim()) {
			searchMode = false;
			load();
			return;
		}
		searchMode = true;
		loading = true;
		try {
			const res = await api.search(term, 60);
			items = res.items;
			total = res.count;
		} catch (e) {
			error = e instanceof Error ? e.message : '搜索失败';
		} finally {
			loading = false;
		}
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

	// Reload on any reactive change (filters or pagination).
	$effect(() => {
		if (searchMode) return;
		load();
	});

	onMount(() => {
		api.meta().then((m) => (meta = m)).catch(() => (meta = null));
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
		三语言 Canonical 数据库 · {meta?.counts.total ?? '—'} 只收录
		{#if meta}
			<span class="faint">（官方 {meta.counts.official} · 扩展 {meta.counts.extended}）</span>
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
		{#if searchMode}
			<span class="search-mode">搜索模式</span>
		{/if}
	</div>

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
		{#each LEVEL_TABS as tab}
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
		<label class="f-control">
			<span class="f-label">属性</span>
			<select class="select" value={attribute ?? ''} onchange={(e) => (attribute = (e.target as HTMLSelectElement).value || null)}>
				<option value="">全部</option>
				{#each meta?.attributes ?? [] as a}
					<option value={a.value}>{a.label_zh} / {a.label_en}</option>
				{/each}
			</select>
		</label>

		<label class="f-control">
			<span class="f-label">类型</span>
			<select class="select" value={typeName ?? ''} onchange={(e) => (typeName = (e.target as HTMLSelectElement).value || null)}>
				<option value="">全部</option>
				{#each meta?.types ?? [] as t}
					<option value={t.name}>{t.name}</option>
				{/each}
			</select>
		</label>

		<label class="f-control">
			<span class="f-label">适应领域</span>
			<select class="select" value={field ?? ''} onchange={(e) => (field = (e.target as HTMLSelectElement).value || null)}>
				<option value="">全部</option>
				{#each meta?.fields ?? [] as f}
					<option value={f.name}>{f.name}</option>
				{/each}
			</select>
		</label>

		<label class="f-control">
			<span class="f-label">所属组织</span>
			<select class="select" value={group ?? ''} onchange={(e) => (group = (e.target as HTMLSelectElement).value || null)}>
				<option value="">全部</option>
				{#each meta?.groups ?? [] as g}
					<option value={g.name}>{g.name_zh ? `${g.name_zh} · ${g.name}` : g.name}</option>
				{/each}
			</select>
		</label>

		<label class="f-control">
			<span class="f-label">X 抗体</span>
			<select class="select" value={xAb === null ? '' : String(xAb)} onchange={(e) => {
				const v = (e.target as HTMLSelectElement).value;
				xAb = v === '' ? null : v === 'true';
			}}>
				<option value="">全部</option>
				<option value="true">是</option>
				<option value="false">否</option>
			</select>
		</label>

		<label class="f-control">
			<span class="f-label">排序</span>
			<select class="select" value={sort} onchange={(e) => (sort = (e.target as HTMLSelectElement).value)}>
				<option value="name">名称</option>
				<option value="id">ID</option>
				<option value="debut">首次登场</option>
				<option value="recent">最近更新</option>
				<option value="level">等级</option>
			</select>
		</label>

		<button class="btn" onclick={resetFilters}>重置筛选</button>
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
		border-radius: var(--radius);
	}
	.search-mode {
		position: absolute;
		right: 12px;
		top: 50%;
		transform: translateY(-50%);
		font-family: var(--mono);
		font-size: 11px;
		color: var(--accent);
		background: rgba(53, 208, 255, 0.12);
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
	.f-control {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.f-label {
		font-family: var(--mono);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 1px;
		color: var(--text-faint);
	}
	.result-count {
		margin: 14px 0 10px;
		color: var(--text-dim);
		font-size: 13px;
	}
</style>
