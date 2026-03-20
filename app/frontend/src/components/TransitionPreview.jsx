/** @fileoverview Mini transition preview for settings page. */
import { useRef, useEffect } from "preact/hooks";

const PREVIEW_SIZE = 64;

/**
 * TransitionPreview — shows a looping CSS transition demo.
 * @param {Object} props
 * @param {string} props.type - "fade" | "slide" | "zoom" | "dissolve" | "none"
 */
export function TransitionPreview({ type }) {
    const containerRef = useRef(null);

    useEffect(() => {
        if (!containerRef.current || type === "none") return;
        const el = containerRef.current;
        const classMap = { fade: "fc-fade", slide: "fc-slide", zoom: "fc-kenburns", dissolve: "fc-dissolve" };
        const cls = classMap[type] || "fc-fade";

        let active = true;
        function animate() {
            if (!active) return;
            el.style.opacity = "0";
            el.className = `fc-preview-box ${cls}-in`;
            el.style.setProperty("--fc-transition-ms", "800ms");
            setTimeout(() => {
                if (!active) return;
                el.className = `fc-preview-box ${cls}-out`;
                setTimeout(() => {
                    if (active) animate();
                }, 1200);
            }, 1200);
        }
        animate();
        return () => { active = false; };
    }, [type]);

    if (type === "none") {
        return (
            <div style={`width:${PREVIEW_SIZE}px;height:${PREVIEW_SIZE}px;background:#111;border:1px solid var(--border-subtle);display:flex;align-items:center;justify-content:center;`}>
                <span class="sh-ansi-dim" style="font-size:0.6rem;">NONE</span>
            </div>
        );
    }

    return (
        <div style={`width:${PREVIEW_SIZE}px;height:${PREVIEW_SIZE}px;position:relative;overflow:hidden;border:1px solid var(--border-subtle);background:#111;`}>
            <div
                ref={containerRef}
                class="fc-preview-box"
                style={`position:absolute;inset:0;background:var(--sh-phosphor);opacity:0;`}
            />
        </div>
    );
}
