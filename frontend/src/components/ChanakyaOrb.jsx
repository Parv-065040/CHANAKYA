import { useRef } from "react";
import { Brain, BookOpenText, Sparkle } from "@phosphor-icons/react";

export function ChanakyaOrb({ compact = false }) {
  const stageRef = useRef(null);
  const faceRef = useRef(null);

  const move = (event) => {
    const stage = stageRef.current;
    const face = faceRef.current;
    if (!stage || !face || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const rect = stage.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    face.style.transform = "rotateX(" + (-y * 8) + "deg) rotateY(" + (x * 10) + "deg) translateZ(22px)";
  };

  const leave = () => {
    if (faceRef.current) faceRef.current.style.transform = "rotateX(0deg) rotateY(0deg) translateZ(0)";
  };

  return (
    <div ref={stageRef} className={`chanakya-orb ${compact ? "chanakya-orb--compact" : ""}`}
      onPointerMove={move} onPointerLeave={leave} aria-label="CHANAKYA wisdom mascot">
      <div className="orb-grid" aria-hidden="true" />
      <div className="orb-ring orb-ring--one" aria-hidden="true" />
      <div className="orb-ring orb-ring--two" aria-hidden="true" />
      <div ref={faceRef} className="orb-mascot">
        <div className="mascot-crown"><Sparkle weight="fill" size={16} /></div>
        <div className="mascot-face">
          <div className="mascot-eyes"><span /><span /></div>
          <div className="mascot-tilak" />
          <div className="mascot-beard" />
          <div className="mascot-mouth" />
        </div>
        <div className="mascot-collar"><BookOpenText size={18} weight="bold" /></div>
        <div className="mascot-brain"><Brain size={17} weight="duotone" /></div>
      </div>
    </div>
  );
}
