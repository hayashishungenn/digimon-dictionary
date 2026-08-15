<script lang="ts">
	import { api } from '$lib/api/client';
	import type { DigimonListItem } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';
	import ErrorState from '$lib/components/ErrorState.svelte';
	import SkeletonGrid from '$lib/components/SkeletonGrid.svelte';
	import { favorites } from '$lib/stores/favorites.svelte';

	let items = $state<DigimonListItem[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Fetch the favorited ids as list items; ids only exist locally (localStorage),
	// so fetch order is the saved order. Bounded by the API (500).
	async function load() {
		loading = true;
		error = null;
		try {
			const res = await api.byIds(favorites.ids);
			items = res.items;
		} catch (e) {
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void favorites.ids;
		load();
	});
</script>

<svelte:head>
	<title>收藏 · DigiDex</title>
</svelte:head>

<div class="breadcrumb" aria-label="面包屑">
	<a href="/">首页</a><span class="sep">/</span>
	<span class="cur mono">收藏</span>
</div>
<h1 class="page-title">收藏 Favorites</h1>
<p class="dim">个人收藏保存在本机浏览器（localStorage），不改变 canonical 数据，也不依赖登录或公网。</p>

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
				<DigimonCard {item} />
			{/each}
		</div>
	{/if}
	{#if favorites.ids.some((id) => !items.some((i) => i.id === id))}
		<p class="faint mono" style="font-size:12px;margin-top:10px">
			{items.length === 0 ? '全部' : '部分'}收藏对应的数码兽不存在或已从数据集中移除。
		</p>
	{/if}
{/if}
