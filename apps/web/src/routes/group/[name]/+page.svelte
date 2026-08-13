<script lang="ts">
	import { api } from '$lib/api/client';
	import type { GroupResponse } from '$lib/api/types';
	import DigimonCard from '$lib/components/DigimonCard.svelte';

	let { params } = $props();
	let name = $derived(decodeURIComponent(params.name));

	let data = $state<GroupResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// reload whenever the group name changes (SvelteKit reuses the component)
	$effect(() => {
		load(name);
	});

	async function load(n: string) {
		loading = true;
		error = null;
		try {
			data = await api.group(n);
		} catch (e) {
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{name} · 所属组织 · DigiDex</title>
</svelte:head>

{#if loading}
	<div class="spinner" aria-label="加载中"></div>
{:else if error}
	<div class="error-box">{error}</div>
{:else if data}
	<h1 class="group-title">所属组织：{name}</h1>
	<p class="dim">成员 {data.count} 只</p>
	<div class="grid">
		{#each data.members as m}
			<DigimonCard item={m} />
		{/each}
	</div>
{/if}
