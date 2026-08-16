<script lang="ts">
	import { api, userMessage } from '$lib/api/client';
	import type { DigimonListItem } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';
	import ErrorState from '$lib/components/ErrorState.svelte';
	import SkeletonGrid from '$lib/components/SkeletonGrid.svelte';
	import { favorites, clearFavorites } from '$lib/stores/favorites.svelte';
	import { clearHistory, clearPersonal, personal, personalCount } from '$lib/stores/personal.svelte';

	let items = $state<DigimonListItem[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let confirmClear = $state(false);
	let reqSeq = 0; // P2-07: only the newest load may update state

	// Fetch the favorited ids as list items; ids only exist locally (localStorage),
	// so fetch order is the saved order. Bounded by the API (500).
	async function load() {
		const my = ++reqSeq;
		loading = true;
		error = null;
		try {
			const res = await api.byIds(favorites.ids);
			if (my !== reqSeq) return; // stale -> drop
			items = res.items;
		} catch (e) {
			if (my !== reqSeq) return;
			error = userMessage(e, '加载失败');
		} finally {
			if (my === reqSeq) loading = false;
		}
	}

	$effect(() => {
		void favorites.ids;
		load();
	});

	// Personal data lives only in localStorage; export is a local JSON download.
	function exportPersonal() {
		const blob = new Blob([JSON.stringify(personal, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'digidex-personal.json';
		a.click();
		URL.revokeObjectURL(url);
	}
</script>

<svelte:head>
	<title>收藏 · DigiDex</title>
</svelte:head>

<div class="breadcrumb" aria-label="面包屑">
	<a href="/">首页</a><span class="sep">/</span>
	<span class="cur mono">收藏</span>
</div>
<h1 class="page-title">收藏 Favorites</h1>
<p class="dim">个人收藏、备注、标签与查询历史保存在本机浏览器（localStorage），不改变 canonical 数据，也不依赖登录或公网。</p>

{#if error}
	<ErrorState message={error} retry={load} />
{:else if favorites.ids.length === 0}
	<div class="empty-card">
		<div class="empty-icon mono">☆</div>
		<p>还没有收藏任何数码兽。</p>
		<p class="faint">在首页卡片或详情页点击 ☆ 即可加入收藏。</p>
		<a class="btn btn-primary" href="/">前往图鉴</a>
	</div>
{:else if loading && items.length === 0}
	<SkeletonGrid count={Math.min(6, favorites.ids.length)} />
{:else}
	<div class="result-count mono">共 {favorites.ids.length} 只收藏</div>
	{#if items.length > 0}
		<div class="grid">
			{#each items as item}
				<div class="fav-card">
					<DigimonCard {item} />
					{#if personalCount(item.id) > 0}
						<span class="personal-hint mono" title="该收藏有个人备注/标签">{personalCount(item.id)} 条个人记录</span>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
	{#if favorites.ids.some((id) => !items.some((i) => i.id === id))}
		<p class="faint mono" style="font-size:12px;margin-top:10px">
			{items.length === 0 ? '全部' : '部分'}收藏对应的数码兽不存在或已从数据集中移除。
		</p>
	{/if}
{/if}

<div class="personal-panel">
	<h2 class="pp-title">个人数据管理（仅本机）</h2>
	<div class="pp-row">
		<div>
			<span class="faint mono" style="font-size:11px">最近查询</span>
			{#if personal.history.length > 0}
				<div class="history-list">
					{#each personal.history as h}<span class="history-chip mono">{h}</span>{/each}
				</div>
			{:else}
				<p class="faint" style="font-size:12px">暂无查询历史。</p>
			{/if}
		</div>
	</div>
	<div class="pp-actions">
		<button class="btn" onclick={clearHistory}>清除查询历史</button>
		<button class="btn" onclick={exportPersonal}>导出个人数据（JSON）</button>
		{#if confirmClear}
			<span class="confirm-inline">
				<span class="faint">确认清空全部收藏/备注/标签/历史？</span>
				<button class="btn btn-danger" onclick={() => { clearPersonal(); clearFavorites(); confirmClear = false; }}>确认清空</button>
				<button class="btn" onclick={() => (confirmClear = false)}>取消</button>
			</span>
		{:else}
			<button class="btn" onclick={() => (confirmClear = true)}>清除全部个人数据</button>
		{/if}
	</div>
</div>


<style>
	.fav-card {
		position: relative;
	}
	.personal-hint {
		display: block;
		margin-top: 4px;
		font-size: 10px;
		color: var(--text-faint);
	}
	.personal-panel {
		margin-top: 28px;
		border: 1px dashed var(--border-strong);
		border-radius: var(--radius);
		padding: 14px 16px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.pp-title {
		margin: 0;
		font-size: 14px;
		font-weight: 700;
		color: var(--text-dim);
	}
	.history-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 6px;
	}
	.history-chip {
		font-size: 11px;
		color: var(--text-dim);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 2px 9px;
	}
	.pp-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}
	.btn-danger {
		border-color: rgba(255, 93, 115, 0.5);
		color: var(--danger);
	}
	.btn-danger:hover {
		background: rgba(255, 93, 115, 0.12);
	}
	.confirm-inline {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
</style>
