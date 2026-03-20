/** @fileoverview Offline tile cache using the Cache API.
 *
 * Cache-first strategy: serve from cache when available, fetch from
 * network otherwise and store the response. On network failure, fall
 * back to cache silently — the map stays usable offline with whatever
 * tiles were previously viewed.
 *
 * Designed for Pi deployment: MAX_CACHED_TILES caps storage so we
 * don't fill the SD card. Oldest entries are pruned first (FIFO by
 * insertion order in the Cache API).
 */

const CACHE_NAME = "framecast-tiles-v1";
const MAX_CACHED_TILES = 500;

/**
 * Fetch a tile URL with cache-first strategy.
 *
 * 1. Check cache — return immediately if hit.
 * 2. Fetch from network — cache the response on success.
 * 3. On network error — try cache again (covers race with going offline).
 *
 * @param {string} url - Tile URL to fetch.
 * @returns {Promise<Response>}
 */
export async function cachedTileFetch(url) {
  try {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(url);
    if (cached) return cached;

    const response = await fetch(url);
    if (response.ok) {
      cache.put(url, response.clone());
    }
    return response;
  } catch (err) {
    // Network failed — try cache one more time (may have been cached
    // between the first check and the fetch attempt).
    try {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(url);
      if (cached) return cached;
    } catch (_e) {
      /* Cache API unavailable (e.g. non-HTTPS without localhost) */
    }
    throw err;
  }
}

/**
 * Prune oldest tiles when cache exceeds MAX_CACHED_TILES.
 *
 * Cache API keys() returns entries in insertion order — we delete
 * from the front (oldest) to stay under the cap.
 */
export async function pruneTileCache() {
  try {
    const cache = await caches.open(CACHE_NAME);
    const keys = await cache.keys();
    if (keys.length > MAX_CACHED_TILES) {
      const toDelete = keys.slice(0, keys.length - MAX_CACHED_TILES);
      await Promise.all(toDelete.map((key) => cache.delete(key)));
    }
  } catch (_e) {
    /* No-op if cache unavailable */
  }
}
