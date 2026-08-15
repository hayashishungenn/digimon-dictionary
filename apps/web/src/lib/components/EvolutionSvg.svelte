<script lang="ts">
	import type { EvolutionGraph } from '$lib/api/types';

	interface Props {
		graph: EvolutionGraph;
		centerId: number;
	}
	let { graph, centerId }: Props = $props();

	// ----- layout -----
	const NODE_W = 96;
	const NODE_H = 92;
	const COL_GAP = 130;
	const ROW_GAP = 20;
	const PAD = 12;

	let layout = $derived(buildLayout(graph, centerId));
	let width = $derived(layout.maxW + PAD * 2);
	let height = $derived(layout.maxH + PAD * 2);
	let positions = $derived(layout.positions);

	// ----- pan / zoom -----
	let scale = $state(1);
	let panX = $state(0);
	let panY = $state(0);
	let dragging = $state(false);
	let lastX = 0;
	let lastY = 0;

	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const el = e.currentTarget as HTMLElement;
		const rect = el.getBoundingClientRect();
		const mx = e.clientX - rect.left;
		const my = e.clientY - rect.top;
		const factor = e.deltaY < 0 ? 1.12 : 0.89;
		const ns = Math.min(3, Math.max(0.25, scale * factor));
		// keep the point under the cursor stationary
		panX = mx - (mx - panX) * (ns / scale);
		panY = my - (my - panY) * (ns / scale);
		scale = ns;
	}

	function onPointerDown(e: PointerEvent) {
		dragging = true;
		lastX = e.clientX;
		lastY = e.clientY;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!dragging) return;
		panX += e.clientX - lastX;
		panY += e.clientY - lastY;
		lastX = e.clientX;
		lastY = e.clientY;
	}

	function onPointerUp() {
		dragging = false;
	}

	function zoomBy(factor: number) {
		scale = Math.min(3, Math.max(0.25, scale * factor));
	}

	function resetView() {
		scale = 1;
		panX = 0;
		panY = 0;
	}
</script>

<div
	class="evo-graph"
	class:dragging
	onwheel={onWheel}
	onpointerdown={onPointerDown}
	onpointermove={onPointerMove}
	onpointerup={onPointerUp}
	onpointerleave={onPointerUp}
	role="img"
	aria-label="进化图谱（滚轮缩放，拖拽平移）"
>
	<svg
		width={width}
		height={height}
		viewBox={`0 0 ${width} ${height}`}
		style="transform: translate({panX}px, {panY}px) scale({scale}); transform-origin: 0 0;"
	>
		{#each graph.edges as e}
			{@const a = positions[String(e.from)]}
			{@const b = positions[String(e.to)]}
			{#if a && b}
				<path
					d={edgePath(a, b)}
					fill="none"
					stroke={e.is_primary_line ? 'var(--accent)' : '#2e4377'}
					stroke-width={e.is_primary_line ? 2 : 1}
					class="edge"
					marker-end="url(#arrow)"
				/>
			{/if}
		{/each}
		<defs>
			<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
				<path d="M0,0 L0,6 L7,3 z" fill="#35d0ff" />
			</marker>
		</defs>
		{#each Object.entries(positions) as [id, p]}
			{@const node = graph.nodes[id]}
			<g class="node" transform={`translate(${p.x}, ${p.y})`}>
				<a href={`/digimon/${node.canonical_slug}`}>
					<rect x="0" y="0" width={NODE_W} height={NODE_H} rx="8" class="node-bg"
						class:center={Number(id) === centerId} />
					<text x={NODE_W / 2} y={NODE_H - 10} text-anchor="middle" class="node-name">
						{node.name_zh_cn ?? node.name_en ?? node.canonical_slug}
					</text>
					{#if node.main_image}
						<image href={node.main_image} x={NODE_W / 2 - 26} y="4" width="52" height="52" preserveAspectRatio="xMidYMid meet" />
					{:else}
						<text x={NODE_W / 2} y="34" text-anchor="middle" class="node-fallback">?</text>
					{/if}
				</a>
			</g>
		{/each}
	</svg>

	<div class="zoom-controls" aria-label="图谱缩放">
		<button class="btn zoom-btn" onclick={() => zoomBy(1.2)} aria-label="放大">＋</button>
		<button class="btn zoom-btn" onclick={() => zoomBy(0.83)} aria-label="缩小">−</button>
		<button class="btn zoom-btn" onclick={resetView} aria-label="重置视图">⟲</button>
	</div>
	<span class="zoom-hint mono faint">滚轮缩放 · 拖拽平移 · 点击节点进入详情</span>
</div>

<style>
	.evo-graph {
		position: relative;
		overflow: hidden;
		cursor: grab;
		touch-action: none;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background:
			radial-gradient(circle at 20% 10%, rgba(53, 208, 255, 0.05), transparent 40%),
			radial-gradient(circle at 90% 90%, rgba(255, 200, 87, 0.05), transparent 40%);
		user-select: none;
	}
	.evo-graph.dragging {
		cursor: grabbing;
	}
	.zoom-controls {
		position: absolute;
		top: 10px;
		right: 10px;
		display: flex;
		gap: 6px;
	}
	.zoom-btn {
		width: 30px;
		height: 30px;
		padding: 0;
		justify-content: center;
		font-size: 15px;
		background: rgba(15, 21, 38, 0.85);
		backdrop-filter: blur(4px);
	}
	.zoom-hint {
		position: absolute;
		bottom: 8px;
		left: 12px;
		font-size: 11px;
		pointer-events: none;
	}
	:global(.node-bg) {
		fill: #16203a;
		stroke: #2e4377;
	}
	:global(.node-bg.center) {
		stroke: #35d0ff;
	}
	:global(.node-name) {
		fill: #e9edf7;
		font-size: 11px;
		font-family: var(--sans);
		pointer-events: none;
	}
	:global(.node-fallback) {
		fill: #66708c;
		font-size: 20px;
	}
	:global(.edge) {
		transition: stroke 0.15s;
	}
</style>

<script module lang="ts">
	export function edgePath(a: { x: number; y: number; cx: number; cy: number }, b: { x: number; y: number; cx: number; cy: number }) {
		const x1 = a.cx;
		const y1 = a.cy;
		const x2 = b.cx;
		const y2 = b.cy;
		const dx = Math.abs(x2 - x1) / 2;
		return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
	}

	export function buildLayout(graph: EvolutionGraph, centerId: number) {
		const NODE_W = 96;
		const NODE_H = 92;
		const COL_GAP = 130;
		const ROW_GAP = 20;
		// BFS undirected from center to assign layers
		const layerOf = new Map<number, number>();
		layerOf.set(centerId, 0);
		const adj = new Map<number, number[]>();
		for (const e of graph.edges) {
			adj.set(e.from, [...(adj.get(e.from) ?? []), e.to]);
			adj.set(e.to, [...(adj.get(e.to) ?? []), e.from]);
		}
		const queue = [centerId];
		let qi = 0;
		while (qi < queue.length) {
			const u = queue[qi++];
			const ul = layerOf.get(u)!;
			for (const v of adj.get(u) ?? []) {
				if (!layerOf.has(v) && graph.nodes[String(v)]) {
					layerOf.set(v, ul + 1);
					queue.push(v);
				}
			}
		}
		const layers = new Map<number, number[]>();
		for (const [id, layer] of layerOf) {
			if (id === centerId) continue;
			layers.set(layer, [...(layers.get(layer) ?? []), id]);
		}
		for (const [k, v] of layers) layers.set(k, v.sort((a, b) => a - b));

		const positions: Record<string, { x: number; y: number; cx: number; cy: number }> = {};
		const maxLayer = Math.max(0, ...layerOf.values());
		positions[String(centerId)] = {
			x: 0,
			y: 0,
			cx: NODE_W / 2,
			cy: NODE_H / 2
		};
		for (let layer = 1; layer <= maxLayer; layer++) {
			const ids = layers.get(layer) ?? [];
			const colX = layer * (NODE_W + COL_GAP);
			const totalH = ids.length * (NODE_H + ROW_GAP) - ROW_GAP;
			ids.forEach((id, i) => {
				const y = (totalH - NODE_H) / 2 + i * (NODE_H + ROW_GAP);
				positions[String(id)] = { x: colX, y, cx: colX + NODE_W / 2, cy: y + NODE_H / 2 };
			});
		}
		const maxW = maxLayer * (NODE_W + COL_GAP) + NODE_W;
		const maxRowCount = Math.max(1, ...[...layers.values()].map((ids) => ids.length));
		const maxH = maxRowCount * (NODE_H + ROW_GAP) - ROW_GAP;
		return { positions, maxW, maxH };
	}
</script>
