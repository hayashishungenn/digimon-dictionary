<script lang="ts">
	import type { EvolutionGraph } from '$lib/api/types';
	import PlaceholderImage from './PlaceholderImage.svelte';
	import EvolutionSvg from './EvolutionSvg.svelte';

	interface Props {
		graph: EvolutionGraph;
		centerId: number;
		canExpand?: boolean;
		onExpand?: () => void;
	}
	let { graph, centerId, canExpand = true, onExpand }: Props = $props();

	let view = $state<'simple' | 'graph'>('simple');

	let center = $derived(graph.nodes[String(centerId)]);
	let inEdges = $derived(graph.edges.filter((e) => e.to === centerId && e.from !== centerId));
	let outEdges = $derived(graph.edges.filter((e) => e.from === centerId && e.to !== centerId));
</script>

<div class="evo">
	<div class="evo-tabs">
		<button class="btn {view === 'simple' ? 'active' : ''}" onclick={() => (view = 'simple')}>简单模式</button>
		<button class="btn {view === 'graph' ? 'active' : ''}" onclick={() => (view = 'graph')}>图谱模式</button>
		{#if view === 'graph' && canExpand}
			<button class="btn" onclick={onExpand}>展开更深一层</button>
		{/if}
	</div>

	{#if view === 'simple'}
		<div class="evo-simple">
			<div>
				<span class="section-title small">全部可能前置</span>
				{#if inEdges.length > 0}
					<div class="evo-row-wrap">
						{#each inEdges as e}
							<a class="evo-node" href={`/digimon/${graph.nodes[String(e.from)].canonical_slug}`}>
								<PlaceholderImage src={graph.nodes[String(e.from)].main_image} alt={graph.nodes[String(e.from)].name_en ?? ''} label="?" />
								<span class="n-block">
									<span class="n-zh">{graph.nodes[String(e.from)].name_zh_cn ?? '—'}</span>
									<span class="n-en">{graph.nodes[String(e.from)].name_en}</span>
								</span>
							</a>
						{/each}
					</div>
				{:else}
					<div class="no-data">暂无已知前置进化</div>
				{/if}
			</div>

			<div class="evo-center">
				<span class="evo-node center">
					<PlaceholderImage src={center?.main_image} alt={center?.name_en ?? ''} label="?" />
					<span class="n-block">
						<span class="n-zh">{center?.name_zh_cn ?? '—'}</span>
						<span class="n-en">{center?.name_en}</span>
					</span>
				</span>
			</div>

			<div>
				<span class="section-title small">全部可能后续</span>
				{#if outEdges.length > 0}
					<div class="evo-row-wrap">
						{#each outEdges as e}
							<a class="evo-node" href={`/digimon/${graph.nodes[String(e.to)].canonical_slug}`}>
								<PlaceholderImage src={graph.nodes[String(e.to)].main_image} alt={graph.nodes[String(e.to)].name_en ?? ''} label="?" />
								<span class="n-block">
									<span class="n-zh">{graph.nodes[String(e.to)].name_zh_cn ?? '—'}</span>
									<span class="n-en">{graph.nodes[String(e.to)].name_en}</span>
								</span>
							</a>
						{/each}
					</div>
				{:else}
					<div class="no-data">暂无已知后续进化</div>
				{/if}
			</div>
		</div>
	{:else}
		{#if graph.edges.length > 0}
			<EvolutionSvg {graph} {centerId} />
		{:else}
			<div class="no-data">没有可展示的进化关系</div>
		{/if}
	{/if}
</div>

<style>
	.evo-tabs {
		display: flex;
		gap: 8px;
		margin-bottom: 12px;
	}
	.section-title.small {
		margin: 14px 0 6px;
	}
	.evo-row-wrap {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.evo-center {
		margin: 16px 0;
	}
	.evo-node.center {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px rgba(53, 208, 255, 0.35);
	}
	.n-block {
		display: flex;
		flex-direction: column;
	}
</style>
