/** @fileoverview QR code component rendered on canvas with phosphor green. */
import { useRef, useEffect } from "preact/hooks";
import qrcode from "qrcode-generator";

/**
 * QRCode -- renders a QR code on a <canvas> element.
 *
 * @param {Object} props
 * @param {string} props.url   - The URL to encode
 * @param {number} [props.size=120] - Canvas size in CSS pixels
 */
export function QRCode({ url, size = 120 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !url) return;

    // Generate QR code (type 0 = auto-detect version, error correction L)
    const qr = qrcode(0, "L");
    qr.addData(url);
    qr.make();

    const moduleCount = qr.getModuleCount();
    const ctx = canvas.getContext("2d");

    // Use higher pixel ratio for sharp rendering
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    ctx.scale(dpr, dpr);

    const cellSize = size / moduleCount;

    // Black background
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, size, size);

    // Phosphor green modules
    ctx.fillStyle = "#00ff88";
    for (let row = 0; row < moduleCount; row++) {
      for (let col = 0; col < moduleCount; col++) {
        if (qr.isDark(row, col)) {
          ctx.fillRect(
            col * cellSize,
            row * cellSize,
            cellSize + 0.5, // slight overlap to prevent subpixel gaps
            cellSize + 0.5,
          );
        }
      }
    }
  }, [url, size]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size + "px", height: size + "px", imageRendering: "pixelated" }}
      aria-label={`QR code for ${url}`}
    />
  );
}
