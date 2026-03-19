/** @fileoverview FrameCast application root — routes phone UI and TV display. */
import { signal } from "@preact/signals";

// Detect surface: TV display (/display/*) vs phone UI (everything else)
const path = signal(window.location.pathname);

export function App() {
  // TODO: implement router
  // Phone: ShNav + pages (Upload, Settings, Map, Update, Onboard)
  // TV: display pages (Slideshow, Welcome, Setup, Boot)
  return null;
}
