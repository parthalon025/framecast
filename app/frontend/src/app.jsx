/** @fileoverview FrameCast application root — routes phone UI and TV display. */
import { render } from "preact";
import { Router, route, navigate } from "./components/Router.jsx";
import { PhoneLayout } from "./components/PhoneLayout.jsx";
import { Upload } from "./pages/Upload.jsx";
import { Settings } from "./pages/Settings.jsx";
import { Map } from "./pages/Map.jsx";
import { Update } from "./pages/Update.jsx";
import { Onboard } from "./pages/Onboard.jsx";
import { Stats } from "./pages/Stats.jsx";
import { Users } from "./pages/Users.jsx";
import { DisplayRouter } from "./display/DisplayRouter.jsx";
import { PinGate } from "./components/PinGate.jsx";
import { detectCapability, applyCapability } from "superhot-ui";

// --- Surface detection ---
// /display* = TV display surface, everything else = phone UI
function isDisplay() {
  return route.value.startsWith("/display");
}

// --- Route definitions ---
const phoneRoutes = [
  { path: "/", component: Upload },
  { path: "/settings", component: Settings },
  { path: "/map", component: Map },
  { path: "/stats", component: Stats },
  { path: "/users", component: Users },
  { path: "/update", component: Update },
  { path: "/setup", component: Onboard },
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
      <PinGate />
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
