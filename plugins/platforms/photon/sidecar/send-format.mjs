// Respect the caller's content type, including Markdown containing URLs.
// Spectrum renders Markdown into native text + UTF-16 style ranges; switching
// URL-bearing Markdown to the text builder exposes its raw formatting markers.
// Actual send failures still use the adapter's existing retry/fallback path.

/** @returns {"markdown"|"text"} */
export function chooseSendFormat(format) {
  return format === "markdown" ? "markdown" : "text";
}
