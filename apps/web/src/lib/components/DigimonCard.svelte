<script lang="ts">
	import type { DigimonListItem } from '$lib/api/types';
	import PlaceholderImage from './PlaceholderImage.svelte';
	import { isFavorite, toggleFavorite } from '$lib/stores/favorites.svelte';
	import { levelLabel, attrLabel } from './Badges.svelte';

	interface Props {
		item: DigimonListItem;
	}
	let { item }: Props = $props();

	function imgSrc(item: DigimonListItem): string | null {
		return item.main_image ?? item.thumbnail ?? null;
	}
</script>

<div class="digimon-card" data-testid="digimon-card">
	<button
		class="fav {isFavorite(item.id) ? 'on' : ''}"
		aria-label={isFavorite(item.id) ? '取消收藏' : '收藏'}
		onclick={() => toggleFavorite(item.id)}
	>{isFavorite(item.id) ? '★' : '☆'}</button>
	<a class="card-link" href={`/digimon/${item.canonical_slug}`}>
		<span class="thumb">
			<PlaceholderImage src={imgSrc(item)} alt={item.name_zh_cn ?? item.name_en ?? item.canonical_slug} />
		</span>
		<span class="info">
			<span class="name-zh">{item.name_zh_cn ?? '—'}</span>
			<span class="name-en">
				{item.name_en ?? item.canonical_slug}
				{#if item.name_ja}<span class="name-ja"> · {item.name_ja}</span>{/if}
			</span>
			<span class="meta">
				{#if item.level}
					<span class="badge level-badge lv-{item.level}">{levelLabel(item.level)}</span>
				{/if}
				{#if item.attribute}
					<span class="badge attr-badge at-{item.attribute}">{attrLabel(item.attribute)}</span>
				{/if}
			</span>
		</span>
	</a>
</div>
