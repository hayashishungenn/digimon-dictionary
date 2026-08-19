<script lang="ts">
	import { onMount } from 'svelte';
	import { api, reviewExportUrl, userMessage, type ReviewListFilters } from '$lib/api/client';
	import type { ReviewCategory, ReviewItem, ReviewStats, ReviewStatus } from '$lib/api/types';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ErrorState from '$lib/components/ErrorState.svelte';
	import SectionHeader from '$lib/components/SectionHeader.svelte';
	import SkeletonGrid from '$lib/components/SkeletonGrid.svelte';

	type ResolutionStatus = Exclude<ReviewStatus, 'open'>;

	const PAGE = 20;
	const STATUS_LABELS: Record<ReviewStatus, string> = {
		open: '待处理 Open',
		resolved: '已解决 Resolved',
		wontfix: '暂不处理 Wontfix',
	};
	const CATEGORY_LABELS: Record<ReviewCategory, string> = {
		external_target: '外部目标',
		matching_failure: '匹配失败',
		conflict: '来源冲突',
		wikitext: '原始 Wikitext',
		other: '其他',
	};
	const CATEGORIES: readonly ReviewCategory[] = [
		'external_target',
		'matching_failure',
		'conflict',
		'wikitext',
		'other',
	];

	let items = $state<ReviewItem[]>([]);
	let stats = $state<ReviewStats | null>(null);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let actionError = $state<string | null>(null);
	let success = $state<string | null>(null);
	let status = $state<ReviewStatus>('open');
	let entityType = $state('');
	let category = $state<ReviewCategory | ''>('');
	let query = $state('');
	let offset = $state(0);
	let notes = $state<Record<number, string>>({});
	let noteErrors = $state<Record<number, string>>({});
	let busyId = $state<number | null>(null);
	let requestSequence = 0;
	let ready = $state(false);

	let pageIndex = $derived(Math.floor(offset / PAGE) + 1);
	let pageCount = $derived(Math.max(1, Math.ceil(total / PAGE)));

	function inputValue(event: Event): string {
		const target = event.currentTarget;
		return target instanceof HTMLInputElement ||
			target instanceof HTMLSelectElement ||
			target instanceof HTMLTextAreaElement
			? target.value
			: '';
	}

	function isStatus(value: string | null): value is ReviewStatus {
		return value === 'open' || value === 'resolved' || value === 'wontfix';
	}

	function isCategory(value: string | null): value is ReviewCategory {
		return value !== null && CATEGORIES.some((candidate) => candidate === value);
	}

	function currentFilters(): ReviewListFilters {
		return {
			status,
			entity_type: entityType || null,
			q: query || null,
			category: category || null,
			limit: PAGE,
			offset,
		};
	}

	function exportUrl(format: 'json' | 'csv'): string {
		return reviewExportUrl({
			format,
			status,
			entity_type: entityType || null,
			q: query || null,
			category: category || null,
		});
	}

	async function load(): Promise<void> {
		const sequence = ++requestSequence;
		loading = true;
		error = null;
		actionError = null;
		try {
			const [list, nextStats] = await Promise.all([api.review(currentFilters()), api.reviewStats()]);
			if (sequence !== requestSequence) return;
			items = list.items;
			total = list.total;
			stats = nextStats;
		} catch (cause: unknown) {
			if (sequence !== requestSequence) return;
			error = userMessage(cause, '复核队列加载失败');
		} finally {
			if (sequence === requestSequence) loading = false;
		}
	}

	function writeUrl(): void {
		const params = new URLSearchParams();
		if (status !== 'open') params.set('status', status);
		if (entityType) params.set('entity_type', entityType);
		if (category) params.set('category', category);
		if (query) params.set('q', query);
		if (offset > 0) params.set('offset', String(offset));
		const encoded = params.toString();
		const nextSearch = encoded ? `?${encoded}` : '';
		if (window.location.search !== nextSearch) {
			history.replaceState(null, '', `${window.location.pathname}${nextSearch}`);
		}
	}

	function applyUrl(params: URLSearchParams): void {
		const nextStatus = params.get('status');
		if (isStatus(nextStatus)) status = nextStatus;
		const nextCategory = params.get('category');
		if (isCategory(nextCategory)) category = nextCategory;
		entityType = params.get('entity_type') ?? '';
		query = params.get('q') ?? '';
		const nextOffset = Number(params.get('offset') ?? '0');
		offset = Number.isInteger(nextOffset) && nextOffset >= 0 ? nextOffset : 0;
	}

	function resetPage(): void {
		offset = 0;
	}

	function setStatus(value: string): void {
		if (isStatus(value)) {
			status = value;
			resetPage();
		}
	}

	function setCategory(value: string): void {
		category = isCategory(value) ? value : '';
		resetPage();
	}

	function setEntityType(value: string): void {
		entityType = value;
		resetPage();
	}

	function setQuery(value: string): void {
		query = value;
		resetPage();
	}

	function previousPage(): void {
		offset = Math.max(0, offset - PAGE);
	}

	function nextPage(): void {
		if (offset + PAGE < total) offset += PAGE;
	}

	function setNote(id: number, value: string): void {
		notes = { ...notes, [id]: value };
		if (noteErrors[id]) {
			const next = { ...noteErrors };
			delete next[id];
			noteErrors = next;
		}
	}

	async function resolveItem(item: ReviewItem, nextStatus: ResolutionStatus): Promise<void> {
		const note = (notes[item.id] ?? '').trim();
		if (!note) {
			noteErrors = { ...noteErrors, [item.id]: '请填写处理备注' };
			return;
		}
		busyId = item.id;
		actionError = null;
		success = null;
		try {
			await api.resolveReview(item.id, nextStatus, note);
			await load();
			success = nextStatus === 'resolved' ? `#${item.id} 已标记为已解决。` : `#${item.id} 已标记为暂不处理。`;
		} catch (cause: unknown) {
			actionError = userMessage(cause, '复核写入失败，请稍后重试');
		} finally {
			busyId = null;
		}
	}

	function detailText(item: ReviewItem): string {
		return JSON.stringify(item.detail ?? {}, null, 2) ?? '{}';
	}

	function countStatus(value: ReviewStatus): number {
		return stats?.by_status[value] ?? 0;
	}

	function emptyTitle(): string {
		return status === 'open' ? '当前没有待处理复核项' : `当前没有${STATUS_LABELS[status]}复核项`;
	}

	function categoryLabel(value: string): string {
		const known = CATEGORIES.find((candidate) => candidate === value);
		return known ? CATEGORY_LABELS[known] : value;
	}

	function sourceLabel(item: ReviewItem): string {
		const direct = item.detail?.source;
		if (typeof direct === 'string') return direct;
		const sources = item.detail?.sources;
		if (Array.isArray(sources)) {
			const names = sources.filter((value): value is string => typeof value === 'string');
			if (names.length > 0) return names.join(', ');
		}
		const unresolved = item.detail?.unresolved;
		if (Array.isArray(unresolved)) {
			const names: string[] = [];
			for (const candidate of unresolved) {
				if (typeof candidate !== 'object' || candidate === null || !('source' in candidate)) continue;
				const source = candidate.source;
				if (typeof source === 'string') names.push(source);
			}
			if (names.length > 0) return names.join(', ');
		}
		return '—';
	}

	$effect(() => {
		if (!ready) return;
		void load();
		writeUrl();
	});

	onMount(() => {
		applyUrl(new URLSearchParams(window.location.search));
		ready = true;
	});
</script>

<svelte:head>
	<title>复核队列 · DigiDex</title>
	<meta name="description" content="DigiDex 本地人工复核队列" />
</svelte:head>

<div class="breadcrumb" aria-label="面包屑">
	<a href="/">首页</a><span class="sep">/</span>
	<span class="cur mono">复核队列</span>
</div>

<h1 class="page-title">人工复核队列 <span class="page-title-en">Review Queue</span></h1>
<p class="dim review-intro">
	这里记录无法安全自动合并、来源存在冲突或仍需人工确认的数据。页面只服务于本机自用，不新增公网账号、鉴权或远程写入。
</p>
<div class="local-notice" role="note">
	<span class="mono">LOCAL ONLY</span>
	<span>解决或暂不处理会写入当前本地 SQLite；原始 detail、来源和 run_id 保留。</span>
</div>

<SectionHeader title="队列概览 Overview" code="REVIEW" />
{#if stats}
	<div class="review-stats" aria-label="复核统计">
		<div class="review-stat review-stat-open" data-testid="review-open-count">
			<strong>{stats.open}</strong><span>待处理 Open</span>
		</div>
		<div class="review-stat">
			<strong>{countStatus('resolved')}</strong><span>已解决 Resolved</span>
		</div>
		<div class="review-stat">
			<strong>{countStatus('wontfix')}</strong><span>暂不处理 Wontfix</span>
		</div>
	</div>
	<div class="review-breakdown">
		<div>
			<h2>按分类 Category</h2>
			<div class="breakdown-list">
				{#each CATEGORIES as value}
					<span><b>{CATEGORY_LABELS[value]}</b><em>{stats.by_category[value] ?? 0}</em></span>
				{/each}
			</div>
		</div>
		<div>
			<h2>按实体 Entity type（仅 open）</h2>
			<div class="breakdown-list">
				{#if Object.entries(stats.by_entity).length > 0}
					{#each Object.entries(stats.by_entity) as [value, count]}
						<span><b>{value}</b><em>{count}</em></span>
					{/each}
				{:else}
					<span class="faint">暂无 open 项</span>
				{/if}
			</div>
		</div>
	</div>
{/if}

<SectionHeader title="筛选与导出 Filters / Export" code="QUERY" />
<div class="review-toolbar">
	<label class="review-field">
		<span>复核状态</span>
		<select class="select" aria-label="复核状态" value={status} onchange={(event) => setStatus(inputValue(event))}>
			<option value="open">待处理 Open</option>
			<option value="resolved">已解决 Resolved</option>
			<option value="wontfix">暂不处理 Wontfix</option>
		</select>
	</label>
	<label class="review-field">
		<span>实体类型</span>
		<input class="input" aria-label="实体类型" value={entityType} placeholder="digimon / edge / game" oninput={(event) => setEntityType(inputValue(event))} />
	</label>
	<label class="review-field review-field-wide">
		<span>关键词</span>
		<input class="input" aria-label="复核关键词" value={query} placeholder="搜索 reason 或 detail" oninput={(event) => setQuery(inputValue(event))} />
	</label>
	<label class="review-field">
		<span>复核分类</span>
		<select class="select" aria-label="复核分类" value={category} onchange={(event) => setCategory(inputValue(event))}>
			<option value="">全部分类</option>
			{#each CATEGORIES as value}
				<option value={value}>{CATEGORY_LABELS[value]}</option>
			{/each}
		</select>
	</label>
	<div class="review-export">
		<span>导出当前筛选</span>
		<div>
			<a class="btn" data-testid="review-export-json" href={exportUrl('json')} download="review_queue.json">JSON</a>
			<a class="btn" data-testid="review-export-csv" href={exportUrl('csv')} download="review_queue.csv">CSV</a>
		</div>
	</div>
</div>

{#if actionError}
	<div class="review-feedback review-feedback-error" role="alert">{actionError}</div>
{/if}
{#if success}
	<div class="review-feedback review-feedback-success" role="status">{success}</div>
{/if}

{#if error}
	<ErrorState message={error} retry={load} />
{:else if loading && items.length === 0}
	<SkeletonGrid count={4} />
{:else if items.length === 0}
	<EmptyState title={emptyTitle()} message="可以切换状态、分类或清空关键词后再检查。" />
{:else}
	<div class="review-list" aria-busy={loading} aria-live="polite">
		{#each items as item (item.id)}
			<article class="review-item" data-testid={`review-item-${item.id}`}>
				<div class="review-item-head">
					<div>
						<span class="review-category mono">{categoryLabel(item.category)}</span>
						<h2>{item.reason}</h2>
					</div>
					<span class="review-id mono">#{item.id}</span>
				</div>
				<div class="review-meta mono">
					<span>entity: {item.entity_type}</span>
					<span>entity_id: {item.entity_id ?? '—'}</span>
					<span>source: {sourceLabel(item)}</span>
					<span>created: {item.created_at ?? '—'}</span>
					<span>run_id: {item.run_id ?? '—'}</span>
				</div>
				<details class="review-detail">
					<summary>查看原始 detail</summary>
					<pre>{detailText(item)}</pre>
				</details>
				{#if item.status === 'open'}
					<div class="review-resolve">
						<label>
							<span>处理备注 <small>必填</small></span>
							<textarea aria-label="处理备注" rows="2" value={notes[item.id] ?? ''} placeholder="说明依据、来源或暂不处理原因" oninput={(event) => setNote(item.id, inputValue(event))}></textarea>
						</label>
						{#if noteErrors[item.id]}<p class="note-error" role="alert">{noteErrors[item.id]}</p>{/if}
						<div class="resolve-actions">
							<button class="btn btn-primary" disabled={busyId === item.id} onclick={() => resolveItem(item, 'resolved')}>标记已解决</button>
							<button class="btn" disabled={busyId === item.id} onclick={() => resolveItem(item, 'wontfix')}>标记暂不处理</button>
						</div>
					</div>
				{:else if item.note}
					<p class="review-note"><b>处理备注：</b>{item.note}</p>
				{/if}
			</article>
		{/each}
	</div>

	<div class="pager" aria-label="复核分页">
		<button class="btn" disabled={offset === 0 || loading} onclick={previousPage}>上一页</button>
		<span class="mono" data-testid="review-page">第 {pageIndex} / {pageCount} 页 · 共 {total} 条</span>
		<button class="btn" disabled={offset + PAGE >= total || loading} onclick={nextPage}>下一页</button>
	</div>
{/if}

<style>
	.page-title-en {
		font-family: var(--mono);
		font-size: 13px;
		font-weight: 500;
		color: var(--text-faint);
		letter-spacing: 1px;
	}
	.review-intro {
		max-width: 920px;
	}
	.local-notice {
		display: flex;
		gap: 10px;
		align-items: baseline;
		margin-top: 14px;
		padding: 10px 12px;
		border: 1px solid rgba(255, 200, 87, 0.35);
		border-radius: var(--radius-sm);
		background: rgba(255, 200, 87, 0.07);
		color: var(--text-dim);
		font-size: 12px;
	}
	.local-notice .mono {
		color: var(--warning);
		font-size: 11px;
		letter-spacing: 1px;
		white-space: nowrap;
	}
	.review-stats {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 10px;
	}
	.review-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 14px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.review-stat strong {
		font-family: var(--mono);
		font-size: 25px;
		color: var(--text);
	}
	.review-stat span {
		font-size: 12px;
		color: var(--text-faint);
	}
	.review-stat-open {
		border-color: rgba(255, 200, 87, 0.55);
	}
	.review-stat-open strong {
		color: var(--warning);
	}
	.review-breakdown {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		margin-top: 12px;
	}
	.review-breakdown > div {
		min-width: 0;
		padding: 12px 14px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.review-breakdown h2 {
		margin: 0 0 8px;
		font-family: var(--mono);
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 1px;
		color: var(--text-faint);
		text-transform: uppercase;
	}
	.breakdown-list {
		display: flex;
		flex-wrap: wrap;
		gap: 7px 14px;
	}
	.breakdown-list span {
		display: inline-flex;
		gap: 6px;
		align-items: baseline;
		font-size: 12px;
		color: var(--text-dim);
	}
	.breakdown-list b {
		font-weight: 500;
	}
	.breakdown-list em {
		font-family: var(--mono);
		font-style: normal;
		color: var(--accent);
	}
	.review-toolbar {
		display: grid;
		grid-template-columns: minmax(140px, 0.8fr) minmax(150px, 1fr) minmax(190px, 1.4fr) minmax(150px, 0.9fr) auto;
		gap: 10px;
		align-items: end;
		padding: 14px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.review-field {
		display: flex;
		min-width: 0;
		flex-direction: column;
		gap: 5px;
	}
	.review-field > span,
	.review-export > span,
	.review-resolve label > span {
		font-family: var(--mono);
		font-size: 10px;
		letter-spacing: 0.8px;
		color: var(--text-faint);
		text-transform: uppercase;
	}
	.review-field .input,
	.review-field .select {
		width: 100%;
		min-width: 0;
	}
	.review-export {
		display: flex;
		min-width: 145px;
		flex-direction: column;
		gap: 5px;
	}
	.review-export > div {
		display: flex;
		gap: 6px;
	}
	.review-feedback {
		margin-top: 12px;
		padding: 9px 12px;
		border-radius: var(--radius-sm);
		font-size: 13px;
	}
	.review-feedback-error {
		border: 1px solid rgba(255, 93, 115, 0.45);
		background: rgba(255, 93, 115, 0.08);
		color: var(--danger);
	}
	.review-feedback-success {
		border: 1px solid rgba(94, 242, 160, 0.4);
		background: rgba(94, 242, 160, 0.08);
		color: var(--success);
	}
	.review-list {
		display: grid;
		gap: 12px;
		margin-top: 14px;
	}
	.review-item {
		min-width: 0;
		padding: 14px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: linear-gradient(180deg, var(--surface-2), var(--surface));
	}
	.review-item-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	.review-item h2 {
		margin: 6px 0 0;
		font-size: 16px;
		line-height: 1.35;
		word-break: break-word;
	}
	.review-category {
		padding: 2px 7px;
		border: 1px solid rgba(255, 200, 87, 0.45);
		border-radius: 4px;
		color: var(--warning);
		font-size: 10px;
		letter-spacing: 0.5px;
	}
	.review-id {
		flex: 0 0 auto;
		color: var(--text-faint);
		font-size: 11px;
	}
	.review-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 5px 14px;
		margin-top: 10px;
		color: var(--text-faint);
		font-size: 10px;
	}
	.review-detail {
		margin-top: 12px;
		border-top: 1px solid rgba(34, 50, 90, 0.7);
		padding-top: 9px;
	}
	.review-detail summary {
		cursor: pointer;
		font-size: 12px;
		color: var(--accent);
	}
	.review-detail pre {
		max-width: 100%;
		margin: 8px 0 0;
		padding: 10px;
		overflow: auto;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: rgba(10, 14, 26, 0.65);
		color: var(--text-dim);
		font-family: var(--mono);
		font-size: 11px;
		white-space: pre-wrap;
		word-break: break-word;
	}
	.review-resolve {
		margin-top: 13px;
		padding-top: 12px;
		border-top: 1px dashed var(--border);
	}
	.review-resolve textarea {
		display: block;
		width: 100%;
		margin-top: 5px;
		resize: vertical;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		color: var(--text);
		font: inherit;
		padding: 8px 10px;
	}
	.review-resolve textarea:focus {
		outline: none;
		border-color: var(--accent);
	}
	.review-resolve small {
		color: var(--warning);
		font-family: var(--sans);
		letter-spacing: 0;
		text-transform: none;
	}
	.note-error {
		margin: 5px 0 0;
		color: var(--danger);
		font-size: 12px;
	}
	.resolve-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 8px;
	}
	.review-note {
		margin: 13px 0 0;
		padding: 9px 10px;
		border-left: 2px solid var(--success);
		background: rgba(94, 242, 160, 0.06);
		color: var(--text-dim);
		font-size: 13px;
		word-break: break-word;
	}
	.review-note b {
		color: var(--success);
	}
	.btn:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	@media (max-width: 980px) {
		.review-toolbar {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.review-field-wide,
		.review-export {
			grid-column: span 2;
		}
	}
	@media (max-width: 600px) {
		.page-title-en {
			display: block;
			margin-top: 3px;
		}
		.local-notice {
			align-items: flex-start;
			flex-direction: column;
			gap: 4px;
		}
		.review-stats,
		.review-breakdown {
			grid-template-columns: 1fr;
		}
		.review-toolbar {
			grid-template-columns: 1fr;
		}
		.review-field-wide,
		.review-export {
			grid-column: auto;
		}
		.review-item-head {
			gap: 8px;
		}
		.review-item h2 {
			font-size: 14px;
		}
	}
</style>
