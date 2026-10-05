import { Database, Graph, ShieldCheck, Sparkle } from "@phosphor-icons/react";

export function ProjectScene() {
  const nodes = [
    { cls: "scene-node scene-node--query", label: "USER QUERY", icon: Sparkle },
    { cls: "scene-node scene-node--route", label: "ROUTE", icon: Graph },
    { cls: "scene-node scene-node--retrieve", label: "HYBRID RETRIEVAL", icon: Database },
    { cls: "scene-node scene-node--validate", label: "VALIDATE", icon: ShieldCheck },
  ];

  return (
    <div className="project-scene" aria-label="CHANAKYA architecture flow">
      <div className="scene-floor" />
      <div className="scene-beam scene-beam--a" />
      <div className="scene-beam scene-beam--b" />
      {nodes.map(({ cls, label, icon: Icon }) => (
        <div className={cls} key={label}>
          <span className="scene-node__icon"><Icon size={16} weight="duotone" /></span>
          <span>{label}</span>
        </div>
      ))}
      <div className="scene-core">
        <div className="scene-core__halo" />
        <div className="scene-core__face"><Sparkle size={22} weight="fill" /></div>
        <span>CHANAKYA</span>
        <small>evidence layer</small>
      </div>
      <div className="scene-tag scene-tag--one">semantic</div>
      <div className="scene-tag scene-tag--two">keyword</div>
      <div className="scene-tag scene-tag--three">numerics</div>
    </div>
  );
}
