/** @fileoverview FrameCast application root — routes phone UI and TV display. */
import { render } from "preact";
import { Router, route, navigate } from "./components/Router.jsx";
import { PhoneLayout } from "./components/PhoneLayout.jsx";
import { Upload } from "./pages/Upload.jsx";
import { DisplayRouter } from "./display/DisplayRouter.jsx";
import { detectCapability, applyCapability } from "superhot-ui";

// --- Surface detection ---
// /display* = TV display surface, everything else = phone UI
function isDisplay() {
  return route.value.startsWith("/display");
}

// --- Placeholder page components ---
function SettingsPage() {
  return <div class="sh-frame" style="padding: 20px;">Settings</div>;
}
function MapPage() {
  return <div class="sh-frame" style="padding: 20px;">Map</div>;
}
function UpdatePage() {
  return <div class="sh-frame" style="padding: 20px;">System Update</div>;
}
function SetupPage() {
  return <div class="sh-frame" style="padding: 20px;">Setup</div>;
}
// --- Route definitions ---
const phoneRoutes = [
  { path: "/", component: Upload },
  { path: "/settings", component: SettingsPage },
  { path: "/map", component: MapPage },
  { path: "/update", component: UpdatePage },
  { path: "/setup", component: SetupPage },
];

const displayRoutes = [
  { path: "/display", component: () => <DisplayRouter /> },
  { path: "*", component: () => <DisplayRouter /> },
];

// --- App shell ---
function App() {
  if (isDisplay()) {
    return <Router routes={displayRoutes} />;
  }
  return (
    <PhoneLayout>
      <Router routes={phoneRoutes} />
    </PhoneLayout>
  );
}

// --- Init ---
const cap = detectCapability();
applyCapability(cap);

// Intercept hash-style links from ShNav and convert to pushState
document.addEventListener("click", (evt) => {
  const anchor = evt.target.closest("a[href]");
  if (!anchor) return;
  const href = anchor.getAttribute("href");
  // Handle hash links from ShNav (href="#/path")
  if (href && href.startsWith("#")) {
    evt.preventDefault();
    navigate(href.slice(1) || "/");
    return;
  }
  // Handle internal pushState links
  if (href && href.startsWith("/") && !href.startsWith("//")) {
    evt.preventDefault();
    navigate(href);
  }
});

render(<App />, document.getElementById("app"));
