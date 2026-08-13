// Favorites store persisted to localStorage (Svelte 5 runes).
const KEY = 'digidex.favorites.v1';

function load(): number[] {
	if (typeof localStorage === 'undefined') return [];
	try {
		const raw = localStorage.getItem(KEY);
		if (!raw) return [];
		const arr = JSON.parse(raw);
		return Array.isArray(arr) ? arr.filter((n) => typeof n === 'number') : [];
	} catch {
		return [];
	}
}

function save(ids: number[]) {
	try {
		localStorage.setItem(KEY, JSON.stringify(ids));
	} catch {
		// ignore quota / privacy-mode failures
	}
}

export const favorites = $state<{ ids: number[] }>({ ids: load() });

export function isFavorite(id: number): boolean {
	return favorites.ids.includes(id);
}

export function toggleFavorite(id: number): boolean {
	const i = favorites.ids.indexOf(id);
	if (i >= 0) {
		favorites.ids.splice(i, 1);
	} else {
		favorites.ids.push(id);
	}
	save(favorites.ids);
	return i < 0;
}
