import { useRef } from "react";

/*
 * CHANAKYA's local MagicCard implementation follows the interaction idea
 * of Magic UI's Magic Card: a pointer-following spotlight on a restrained
 * card surface. Kept local so the frontend has no registry/runtime dependency.
 */
export function MagicCard({ children, className = "", ...props }) {
  const ref = useRef(null);

  const move = (event) => {
    const el = ref.current;
    if (!el || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${event.clientX - rect.left}px`);
    el.style.setProperty("--my", `${event.clientY - rect.top}px`);
  };

  const leave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--mx", "50%");
    el.style.setProperty("--my", "50%");
  };

  return (
    <div
      ref={ref}
      className={`magic-card ${className}`}
      onPointerMove={move}
      onPointerLeave={leave}
      {...props}
    >
      <div className="magic-card__spotlight" aria-hidden="true" />
      <div className="magic-card__content">{children}</div>
    </div>
  );
}
