/* Flect's face in the AI console: the logo in a circle that hops on every word it speaks. */
import { useImperativeHandle, useRef, useState, type Ref } from "react";
import { cn } from "@/lib/utils";

export type OrbState = "idle" | "thinking" | "speaking" | "listening";

export interface OrbHandle {
  /** One hop. `strength` ~0.4 (short word) to ~1.4 (long word). */
  bounce: (strength?: number) => void;
}

const reducedMotion = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Shown until the PNG logo is in place (web/public/flect-logo.png): Flect's mark, a ray meeting a surface. */
function Mark() {
  return (
    <svg viewBox="0 0 24 24" className="size-full" aria-hidden>
      <rect width="24" height="24" className="fill-foreground" />
      <path d="M6.6 7.2 12 14.6l5.4-7.4" fill="none" stroke="var(--iris)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.2 17.4h11.6" stroke="var(--background)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function FlectOrb({
  state,
  onClick,
  label,
  ref,
  className,
}: {
  state: OrbState;
  onClick?: () => void;
  label: string;
  ref?: Ref<OrbHandle>;
  className?: string;
}) {
  const lift = useRef<HTMLSpanElement>(null);
  const floor = useRef<HTMLSpanElement>(null);
  const halo = useRef<HTMLSpanElement>(null);
  const [logo, setLogo] = useState(true);

  useImperativeHandle(ref, () => ({
    bounce(strength = 1) {
      const s = Math.min(1.4, Math.max(0.4, strength));
      halo.current?.animate(
        [
          { transform: "scale(1)", opacity: 0.32 + 0.2 * s },
          { transform: `scale(${1.08 + 0.06 * s})`, opacity: 0 },
        ],
        { duration: 560, easing: "cubic-bezier(.2,.7,.3,1)" },
      );
      if (reducedMotion()) return;
      const h = 7 + 9 * s;
      lift.current?.animate(
        [
          { transform: "translateY(0) scale(1, 1)" },
          { transform: `translateY(${-h}px) scale(0.99, 1.025)`, offset: 0.38, easing: "cubic-bezier(.3,0,.6,1)" },
          { transform: "translateY(0) scale(1.03, 0.97)", offset: 0.76, easing: "cubic-bezier(.3,.6,.4,1)" },
          { transform: "translateY(0) scale(1, 1)" },
        ],
        { duration: 330, easing: "cubic-bezier(.25,.8,.35,1)" },
      );
      floor.current?.animate(
        [
          { transform: "scaleX(1)", opacity: 1 },
          { transform: `scaleX(${1 - 0.18 * s})`, opacity: 0.55, offset: 0.38 },
          { transform: "scaleX(1.04)", opacity: 1, offset: 0.76 },
          { transform: "scaleX(1)", opacity: 1 },
        ],
        { duration: 330 },
      );
    },
  }));

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <button type="button" onClick={onClick} aria-label={label} title={label} data-state={state} className="orb group relative size-[clamp(176px,24vw,236px)] rounded-full focus-visible:outline-offset-8">
        <span ref={lift} className="orb-lift absolute inset-0 block">
          <span className="orb-ripple absolute inset-0 rounded-full" aria-hidden />
          <span className="orb-ripple orb-ripple-late absolute inset-0 rounded-full" aria-hidden />
          <span ref={halo} className="absolute inset-0 rounded-full bg-iris opacity-0 blur-[18px]" aria-hidden />
          <span className="orb-sweep absolute -inset-[9px] rounded-full" aria-hidden />
          <span className="orb-face relative block size-full overflow-hidden rounded-full border bg-card">
            {logo ? (
              <img src="/static/flect-logo.png" alt="" draggable={false} onError={() => setLogo(false)} className="size-full object-cover select-none" />
            ) : (
              <Mark />
            )}
          </span>
        </span>
      </button>
      <span ref={floor} className="orb-floor mt-5 block h-3 w-[clamp(96px,13vw,128px)] rounded-[50%]" aria-hidden />
    </div>
  );
}
