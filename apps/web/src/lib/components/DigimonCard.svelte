<script lang="ts">
	import type { DigimonListItem } from '$lib/api/types';
	import { api } from '$lib/api/client';
	import PlaceholderImage from './PlaceholderImage.svelte';
	import { isFavorite, toggleFavorite } from '$lib/stores/favorites.svelte';
	import { levelLabel, attrLabel } from './Badges.svelte';

	interface Props {
		item: DigimonListItem;
	}
	let { item }: Props = $props();

	// list cards use the local thumbnail (served by the API), falling back to the
	// main image URL, then the placeholder — a load failure never breaks the card.
	function imgSrc(item: DigimonListItem): string | null {
		if (item.thumbnail) return api.imageUrl(item.thumbnail);
		return item.main_image ?? null;
	}

	// Chinese-name provenance status shown as a small tag (UI-P0-2): only the
	// non-official statuses get a tag, so a missing/community/unverified name is
	// never presented as official.
	let zhStatus = $derived.by(() => {
		switch (item.name_zh_cn_status) {
			case 'community':
				return { label: '社区', title: '社区通用译名' };
			case 'transliteration':
				return { label: '音译', title: '音译/自动生成，未验证，非官方定名' };
			case 'unverified':
				return { label: '未验证', title: '未验证，非官方定名' };
			default:
				return null; // official (or unknown) — no tag
		}
	});
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
			<span class="name-zh">
				{item.name_zh_cn ?? '—'}
				{#if zhStatus}<span class="name-tag" title={zhStatus.title}>{zhStatus.label}</span>{/if}
			</span>
			<span class="name-en">
				{item.name_en ?? item.canonical_slug}
			</span>
			{#if item.name_ja}<span class="name-ja">{item.name_ja}</span>{/if}
			<span class="card-meta">
				<span class="meta-badges">
					{#if item.level}
						<span class="badge level-badge lv-{item.level}">{levelLabel(item.level)}</span>
					{/if}
					{#if item.attribute}
						<span class="badge attr-badge at-{item.attribute}">{attrLabel(item.attribute)}</span>
					{/if}
				</span>
				{#if item.is_official_reference}
					<span class="coll-badge official" title="官方 Reference Book 已收录">官方</span>
				{:else}
					<span class="coll-badge extended" title="扩展集合（官方未收录）">扩展</span>
				{/if}
			</span>
			<span class="card-code mono">#{item.id} · {item.canonical_slug}</span>
		</span>
	</a>
</div>
