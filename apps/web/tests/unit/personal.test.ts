import { describe, it, expect, beforeEach, vi } from 'vitest';

const KEY = 'digidex.personal.v1';

async function loadStore() {
	vi.resetModules();
	return await import('$lib/stores/personal.svelte');
}

describe('personal store (localStorage, never canonical)', () => {
	beforeEach(() => localStorage.clear());

	it('notes are saved and cleared', async () => {
		const s = await loadStore();
		s.setNote(1, '  my research note  ');
		expect(s.getNote(1)).toBe('my research note');
		s.setNote(1, '');
		expect(s.getNote(1)).toBe('');
		expect(JSON.parse(localStorage.getItem(KEY) ?? '{}').notes).toEqual({});
	});

	it('tags add/dedupe/remove', async () => {
		const s = await loadStore();
		expect(s.addTag(1, ' 主线 ')).toBe(true);
		expect(s.addTag(1, '主线')).toBe(false); // deduped
		expect(s.getTags(1)).toEqual(['主线']);
		s.removeTag(1, '主线');
		expect(s.getTags(1)).toEqual([]);
	});

	it('query history records, dedupes, and caps', async () => {
		const s = await loadStore();
		s.recordQuery('亚古兽');
		s.recordQuery('Agumon');
		s.recordQuery('亚古兽'); // moves to front
		expect(s.personal.history[0]).toBe('亚古兽');
		for (let i = 0; i < 25; i++) s.recordQuery(`q${i}`);
		expect(s.personal.history.length).toBeLessThanOrEqual(20);
	});

	it('recovers safely from corrupted localStorage', async () => {
		localStorage.setItem(KEY, 'not-json{');
		const s = await loadStore();
		expect(s.personal.history).toEqual([]);
		expect(s.getNote(5)).toBe('');
	});

	it('clearPersonal wipes notes, tags, and history', async () => {
		const s = await loadStore();
		s.setNote(1, 'x');
		s.addTag(1, 't');
		s.recordQuery('亚古兽');
		s.clearPersonal();
		expect(s.personal).toEqual({ notes: {}, tags: {}, history: [] });
	});
});
