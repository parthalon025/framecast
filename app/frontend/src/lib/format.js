import { formatTime } from "superhot-ui";

/**
 * Format an ISO datetime string to piOS display format.
 * Returns an em-dash for null/invalid input.
 *
 * @param {string|null} isoStr
 * @returns {string}
 */
export function fmtDateTime(isoStr) {
  if (!isoStr) return "\u2014";
  const ts = new Date(isoStr).getTime();
  if (isNaN(ts)) return "\u2014";
  return formatTime(ts, "date") + " " + formatTime(ts, "compact");
}
