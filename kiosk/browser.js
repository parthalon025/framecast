#!/usr/bin/env gjs
// GJS script: fullscreen WebKit browser for FrameCast kiosk display
//
// Opens a chromeless, fullscreen GTK window with WebKit rendering the
// FrameCast display page.  Retries on load failure every 5 seconds.

imports.gi.versions.Gtk = '3.0';
imports.gi.versions.WebKit2 = '4.1';
const { Gtk, WebKit2, GLib, Gdk } = imports.gi;

const WEB_PORT = ARGV[0] || '8080';
const TARGET_URI = `http://localhost:${WEB_PORT}/display`;
const RETRY_INTERVAL_MS = 5000;

Gtk.init(null);

// --- Window setup ---
const win = new Gtk.Window({ type: Gtk.WindowType.TOPLEVEL });
win.set_title('FrameCast');
win.fullscreen();

// Dark background so blank screen isn't white between loads
const cssProvider = new Gtk.CssProvider();
cssProvider.load_from_data('window { background-color: #000000; }');
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(),
    cssProvider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
);

// --- WebView setup ---
const settings = new WebKit2.Settings();
// Disable scrollbars — kiosk display should never scroll
settings.set_enable_smooth_scrolling(false);
settings.set_enable_javascript(true);
settings.set_enable_page_cache(true);

const webview = new WebKit2.WebView();
webview.set_settings(settings);

// Set dark background on the webview itself
const bgColor = new Gdk.RGBA();
bgColor.parse('#000000');
webview.set_background_color(bgColor);

// Inject CSS to hide scrollbars once the page loads
webview.connect('load-changed', (_wv, event) => {
    if (event === WebKit2.LoadEvent.FINISHED) {
        const css = '::-webkit-scrollbar { display: none !important; } '
                  + 'html, body { overflow: hidden !important; } '
                  + '* { cursor: none !important; }';
        webview.run_javascript(
            `(function() {
                var s = document.createElement('style');
                s.textContent = ${JSON.stringify(css)};
                document.head.appendChild(s);
            })();`,
            null, null
        );
    }
});

// --- Retry on load failure (with limit to avoid infinite black screen) ---
let retrySourceId = 0;
let failureCount = 0;
const MAX_RETRIES = 12; // 12 × 5s = 60s before giving up (systemd restarts)

webview.connect('load-failed', (_wv, _event, _uri, error) => {
    failureCount++;
    log(`FrameCast: load failed (attempt ${failureCount}/${MAX_RETRIES}: ${error.message})`);

    if (failureCount > MAX_RETRIES) {
        log('FrameCast: max retries exceeded, exiting (systemd will restart)');
        Gtk.main_quit();
        return true;
    }

    if (retrySourceId === 0) {
        retrySourceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RETRY_INTERVAL_MS, () => {
            retrySourceId = 0;
            webview.load_uri(TARGET_URI);
            return GLib.SOURCE_REMOVE;
        });
    }
    return true; // handled
});

// Reset failure count on successful load
webview.connect('load-changed', (_wv, event) => {
    if (event === WebKit2.LoadEvent.FINISHED) {
        failureCount = 0;
    }
});

// --- Assemble and launch ---
win.add(webview);
win.show_all();
webview.load_uri(TARGET_URI);

win.connect('destroy', () => {
    if (retrySourceId !== 0) {
        GLib.source_remove(retrySourceId);
    }
    Gtk.main_quit();
});

Gtk.main();
