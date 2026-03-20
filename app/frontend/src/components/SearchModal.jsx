/** @fileoverview SearchModal — full-text search overlay with debounced input and compact results. */
import { signal } from "@preact/signals";
import { useEffect, useRef, useCallback } from "preact/hooks";
import { fetchWithTimeout } from "../lib/fetch.js";

/** Whether the search modal is open. */
export const searchOpen = signal(false);

/** Open the search modal. */
export function openSearch() {
  searchOpen.value = true;
}

/** Close the search modal. */
export function closeSearch() {
  searchOpen.value = false;
  searchQuery.value = "";
  searchResults.value = [];
  searchLoading.value = false;
}

const searchQuery = signal("");
const searchResults = signal([]);
const searchLoading = signal(false);
const searchError = signal("");

/**
 * SearchModal — modal overlay with debounced FTS5 search.
 *
 * @param {object} props
 * @param {Function} [props.onSelect] - Called with photo object when a result is tapped
 */
export function SearchModal({ onSelect }) {
  const inputRef = useRef(null);
  const debounceRef = useRef(null);

  // Focus input on open
  useEffect(() => {
    if (searchOpen.value && inputRef.current) {
      inputRef.current.focus();
    }
  }, [searchOpen.value]);

  // ESC to close
  useEffect(() => {
    if (!searchOpen.value) return;
    function handleKey(evt) {
      if (evt.key === "Escape") closeSearch();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [searchOpen.value]);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const doSearch = useCallback((query) => {
    if (!query.trim()) {
      searchResults.value = [];
      searchLoading.value = false;
      searchError.value = "";
      return;
    }
    searchLoading.value = true;
    searchError.value = "";
    fetchWithTimeout(`/api/search?q=${encodeURIComponent(query.trim())}`)
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
      })
      .then((data) => {
        searchResults.value = data.photos || [];
        searchLoading.value = false;
      })
      .catch((err) => {
        console.warn("SearchModal: fetch failed", err);
        searchError.value = "SEARCH FAULT";
        searchLoading.value = false;
      });
  }, []);

  function handleInput(evt) {
    const val = evt.target.value;
    searchQuery.value = val;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 300);
  }

  function handleOverlayClick(evt) {
    if (evt.target === evt.currentTarget) closeSearch();
  }

  function handleResultClick(photo) {
    if (onSelect) onSelect(photo);
    closeSearch();
  }

  if (!searchOpen.value) return null;

  const results = searchResults.value;
  const loading = searchLoading.value;
  const error = searchError.value;
  const query = searchQuery.value;

  return (
    <div
      class="sh-modal-overlay fc-search-overlay"
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-label="Search photos"
      style="z-index: 150; background: rgba(0,0,0,0.92); display: flex; flex-direction: column; align-items: center; padding-top: calc(24px + env(safe-area-inset-top, 0px));"
    >
      <div
        class="fc-search-container"
        style="width: 100%; max-width: 480px; padding: 0 16px;"
        onClick={(evt) => evt.stopPropagation()}
      >
        {/* Header */}
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
          <span
            style="font-family: var(--font-mono, monospace); font-size: 0.85rem; letter-spacing: 0.1em; color: var(--sh-phosphor, #39ff14);"
          >
            SEARCH
          </span>
          <button
            type="button"
            onClick={closeSearch}
            aria-label="Close search"
            style="background: none; border: none; color: var(--sh-phosphor, #39ff14); font-family: var(--font-mono, monospace); font-size: 1rem; cursor: pointer; padding: 4px 8px; min-width: 44px; min-height: 44px; display: flex; align-items: center; justify-content: center;"
          >
            X
          </button>
        </div>

        {/* Search input */}
        <input
          ref={inputRef}
          class="sh-input"
          type="text"
          placeholder="FILENAME, TAG, OR ALBUM..."
          value={query}
          onInput={handleInput}
          autocomplete="off"
          autocorrect="off"
          spellcheck={false}
          style="width: 100%; font-size: 0.9rem; padding: 10px 12px; font-family: var(--font-mono, monospace); box-sizing: border-box;"
        />

        {/* Status line */}
        <div
          style="font-family: var(--font-mono, monospace); font-size: 0.75rem; margin-top: 8px; min-height: 1.2em;"
        >
          {loading && (
            <span class="sh-ansi-dim">SEARCHING...</span>
          )}
          {error && (
            <span style="color: var(--sh-threat, #ff3333);">{error}</span>
          )}
          {!loading && !error && query.trim() && results.length === 0 && (
            <span class="sh-ansi-dim">NO RESULTS</span>
          )}
          {!loading && !error && results.length > 0 && (
            <span class="sh-ansi-dim">{results.length} FOUND</span>
          )}
        </div>

        {/* Results list */}
        <div
          class="fc-search-results"
          style="margin-top: 8px; max-height: calc(100dvh - 180px); overflow-y: auto; -webkit-overflow-scrolling: touch;"
        >
          {results.map((photo) => (
            <button
              key={photo.id}
              type="button"
              class="fc-search-result sh-clickable"
              onClick={() => handleResultClick(photo)}
              style="display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px; background: none; border: none; border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.08)); cursor: pointer; text-align: left; color: inherit; font-family: var(--font-mono, monospace);"
            >
              <img
                src={`/thumbnail/${photo.name || photo.filename}`}
                onError={(evt) => { evt.target.src = `/media/${photo.name || photo.filename}`; evt.target.onerror = null; }}
                alt={photo.name || photo.filename}
                loading="lazy"
                style="width: 48px; height: 48px; object-fit: cover; border-radius: 3px; flex-shrink: 0;"
              />
              <div style="min-width: 0; flex: 1;">
                <div style="font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--sh-phosphor, #39ff14);">
                  {photo.name || photo.filename}
                </div>
                <div class="sh-ansi-dim" style="font-size: 0.7rem; margin-top: 2px;">
                  {photo.size_human || ""}
                  {photo.is_video ? " VIDEO" : ""}
                  {photo.is_favorite ? " FAV" : ""}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
