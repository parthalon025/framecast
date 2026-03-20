/** @fileoverview Ambient clock — superhot-ui styled screensaver for idle TV display. */
import { useState, useEffect } from "preact/hooks";

function pad(n) { return String(n).padStart(2, "0"); }

export function AmbientClock() {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const hours = pad(now.getHours());
  const minutes = pad(now.getMinutes());
  const seconds = pad(now.getSeconds());

  const dateStr = now.toLocaleDateString("en-US", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  }).toUpperCase();

  return (
    <div class="fc-ambient-clock">
      <div class="fc-clock-time">
        <span class="fc-clock-digits">{hours}</span>
        <span class="fc-clock-separator">:</span>
        <span class="fc-clock-digits">{minutes}</span>
        <span class="fc-clock-separator fc-clock-separator--seconds">:</span>
        <span class="fc-clock-digits fc-clock-digits--seconds">{seconds}</span>
      </div>
      <div class="fc-clock-date">{dateStr}</div>
    </div>
  );
}
