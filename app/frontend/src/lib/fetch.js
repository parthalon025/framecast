/**
 * Fetch wrapper with configurable timeout and offline detection.
 *
 * Default timeout: 15s for normal requests, 60s for uploads.
 * Throws with piOS-style messages: "TIMEOUT", "OFFLINE", "RATE LIMITED. RETRY IN {X}s".
 */

const DEFAULT_TIMEOUT = 15000;
const UPLOAD_TIMEOUT = 60000;

/**
 * Fetch with timeout via AbortController.
 *
 * @param {string} url
 * @param {RequestInit & { timeout?: number }} [opts]
 * @returns {Promise<Response>}
 */
export async function fetchWithTimeout(url, opts = {}) {
  // Offline detection
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    throw new Error("OFFLINE");
  }

  const timeout = opts.timeout || DEFAULT_TIMEOUT;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  // Remove custom props before passing to native fetch
  const fetchOpts = { ...opts, signal: controller.signal };
  delete fetchOpts.timeout;

  try {
    const res = await fetch(url, fetchOpts);

    // Rate limit handling — backend sends retry_after in JSON body
    if (res.status === 429) {
      let retryAfter = 30;
      try {
        const body = await res.json();
        retryAfter = body.retry_after || 30;
      } catch (_) {}
      throw new Error(`RATE LIMITED. RETRY IN ${retryAfter}s`);
    }

    return res;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("TIMEOUT");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Fetch with upload-appropriate timeout (60s).
 *
 * @param {string} url
 * @param {RequestInit & { timeout?: number }} [opts]
 * @returns {Promise<Response>}
 */
export function fetchUpload(url, opts = {}) {
  return fetchWithTimeout(url, { timeout: UPLOAD_TIMEOUT, ...opts });
}
