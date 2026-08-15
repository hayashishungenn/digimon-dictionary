<script lang="ts">
	import { api } from '$lib/api/client';
	import type { GroupResponse } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';
	import ErrorState from '$lib/components/ErrorState.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import SkeletonGrid from '$lib/components/SkeletonGrid.svelte';

	let { params } = $props();
	let name = $derived(decodeURIComponent(params.name));

	let data = $state<GroupResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let reqSeq = 0;

	// reload whenever the group name changes (SvelteKit reuses the component);
	// a stale response must never overwrite a newer one (T6.1)
	$effect(() => {
		load(name);
	});

	async function load(n: string) {
		const my = ++reqSeq;
		loading = true;
		error = null;
		try {
			const res = await api.group(n);
			if (my !== reqSeq) return;
			data = res;
		} catch (e) {
			if (my !== reqSeq) return;
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			if (my === reqSeq) loading = false;
		}
	}
</script>

<svelte:head>
	<title>{name} · 所属组织 · DigiDex</title>
</svelte:head>

{#if loading}
	<SkeletonGrid count={12} />
{:else if error}
	<ErrorState message="加载组织失败" retry={() => load(name)} />
{:else if data}
	<div class="breadcrumb" aria-label="面包屑">
		<a href="/">首页</a><span class="sep">/</span>
		<a href="/">图鉴</a><span class="sep">/</span>
		<span class="cur mono">{name}</span>
	</div>
	<h1 class="group-title">所属组织：{name}</h1>
	<p class="dim">成员 {data.count} 只</p>
	{#if data.members.length > 0}
		<div class="grid">
			{#each data.members as m}
				<DigimonCard item={m} />
			{/each}
		</div>
	{:else}
		<EmptyState title="该组织暂无成员记录" message="没有可展示的数据。" />
	{/if}
{/if}
