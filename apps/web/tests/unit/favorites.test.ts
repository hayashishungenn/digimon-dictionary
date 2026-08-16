import { describe, it, expect, beforeEach, vi } from 'vitest';

const KEY = 'digidex.favorites.v1';

async function loadStore() {
	vi.resetModules();
	return await import('$lib/stores/favorites.svelte');
}

describe('favorites store (localStorage persistence)', () => {
	beforeEach(() => localStorage.clear());

	it('starts empty', async () => {
		const { isFavorite } = await loadStore();
		expect(isFavorite(1)).toBe(false);
	});

	it('toggles a favorite on and off', async () => {
		const { isFavorite, toggleFavorite } = await loadStore();
		expect(toggleFavorite(42)).toBe(true);
		expect(isFavorite(42)).toBe(true);
		expect(toggleFavorite(42)).toBe(false);
		expect(isFavorite(42)).toBe(false);
	});

	it('persists to localStorage', async () => {
		const { toggleFavorite } = await loadStore();
		toggleFavorite(7);
		toggleFavorite(9);
		expect(JSON.parse(localStorage.getItem(KEY) ?? '[]')).toEqual([7, 9]);
	});

	it('restores favorites from localStorage on init', async () => {
		localStorage.setItem(KEY, JSON.stringify([11, 22]));
		const { isFavorite } = await loadStore();
		expect(isFavorite(11)).toBe(true);
		expect(isFavorite(22)).toBe(true);
	});

	it('ignores corrupted localStorage', async () => {
		localStorage.setItem(KEY, 'not-json{');
		const { isFavorite } = await loadStore();
		expect(isFavorite(1)).toBe(false);
	});

	it('clearFavorites empties and persists (survives reload)', async () => {
		const store = await loadStore();
		store.toggleFavorite(7);
		store.toggleFavorite(9);
		expect(store.isFavorite(7)).toBe(true);
		store.clearFavorites();
		expect(store.isFavorite(7)).toBe(false);
		expect(JSON.parse(localStorage.getItem(KEY) ?? '[]')).toEqual([]);
	});
});
