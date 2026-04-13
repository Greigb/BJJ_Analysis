import { useState } from "react";

const taxonomy = [
  {
    id: "standing",
    label: "Standing",
    color: "#6B7280",
    icon: "🧍",
    positions: [
      { name: "Neutral Stance", techniques: ["Single leg", "Double leg", "Snap down", "Arm drag"] },
      { name: "Clinch / Collar Tie", techniques: ["Inside trip", "Body lock takedown", "Ankle pick", "Knee tap"] },
      { name: "Over-Under / Body Lock", techniques: ["Hip toss", "Mat return", "Outside trip"] },
      { name: "Guard Pull (transitional)", techniques: ["Seated guard pull", "Jump guard", "Imanari roll entry"] },
    ],
  },
  {
    id: "open-guard",
    label: "Open Guard (Bottom)",
    color: "#3B82F6",
    icon: "🛡",
    positions: [
      { name: "Closed Guard", techniques: ["Armbar", "Triangle", "Kimura", "Hip bump sweep", "Guillotine", "Omoplata"] },
      { name: "Half Guard", techniques: ["Knee shield", "Underhook sweep", "Lockdown", "Electric chair", "Dogfight"] },
      { name: "Butterfly Guard", techniques: ["Hook sweep", "Guillotine", "Arm drag to back", "X-guard entry"] },
      { name: "De La Riva", techniques: ["DLR sweep", "Berimbolo", "Kiss of the dragon", "Back take"] },
      { name: "Spider Guard", techniques: ["Triangle setup", "Omoplata", "Balloon sweep", "Lasso transition"] },
      { name: "Lasso Guard", techniques: ["Lasso sweep", "Omoplata", "Triangle"] },
      { name: "X-Guard", techniques: ["Technical standup sweep", "Ankle pick sweep", "Single leg X entry"] },
      { name: "Single Leg X / Ashi Garami", techniques: ["Straight ankle lock", "Inside heel hook", "Outside heel hook", "Toe hold", "Honey hole entry"] },
      { name: "Rubber Guard", techniques: ["Gogoplata", "Omoplata", "Mission control triangle"] },
      { name: "Seated / Open Guard (generic)", techniques: ["Collar drag", "Shin-to-shin", "Ankle pick"] },
      { name: "50/50", techniques: ["Heel hook", "Kneebar", "Toe hold", "Sweep to top 50/50"] },
      { name: "Worm Guard / Lapel Guard", techniques: ["Sweep variations", "Back take", "Omoplata"] },
    ],
  },
  {
    id: "guard-top",
    label: "Inside Guard (Top)",
    color: "#F59E0B",
    icon: "⬆",
    positions: [
      { name: "Closed Guard (top)", techniques: ["Guard break", "Stack pass", "Log splitter", "Can opener (illegal in some rulesets)"] },
      { name: "Half Guard (top)", techniques: ["Crossface", "Underhook denial", "Knee slide pass", "Smash pass"] },
      { name: "Butterfly (top)", techniques: ["Smash pass", "Leg drag", "Backstep pass"] },
      { name: "Open Guard (top — standing)", techniques: ["Toreando pass", "Leg drag", "Long step", "Knee slide"] },
      { name: "DLR / Spider (top)", techniques: ["Strip grips", "Knee slide", "Smash pass", "Leg drag"] },
      { name: "Headquarters position", techniques: ["Knee slide", "Leg weave", "Smash pass", "Backstep to leg lock"] },
    ],
  },
  {
    id: "dominant-top",
    label: "Dominant Positions (Top)",
    color: "#10B981",
    icon: "👑",
    positions: [
      { name: "Side Control", techniques: ["Americana", "Kimura", "Arm triangle", "Baseball choke", "Mount transition", "North-south transition"] },
      { name: "Mount", techniques: ["Cross collar choke", "Armbar", "Mounted triangle", "Ezekiel choke", "Arm triangle setup"] },
      { name: "Back Mount (hooks in)", techniques: ["Rear naked choke", "Bow & arrow choke", "Armbar", "Short choke"] },
      { name: "Back Mount (body triangle)", techniques: ["RNC", "Collar choke", "Armbar"] },
      { name: "Knee on Belly", techniques: ["Armbar", "Baseball choke", "Far side armbar", "Clock choke", "Mount transition"] },
      { name: "North-South", techniques: ["North-south choke", "Kimura", "Farside armbar", "Side control return"] },
      { name: "Crucifix", techniques: ["Neck crank", "Armbar", "Collar choke"] },
    ],
  },
  {
    id: "inferior-bottom",
    label: "Inferior Positions (Bottom)",
    color: "#EF4444",
    icon: "⚠",
    positions: [
      { name: "Bottom Side Control", techniques: ["Frame escape to guard", "Underhook escape", "Ghost escape", "Shrimp to half guard"] },
      { name: "Bottom Mount", techniques: ["Elbow-knee escape", "Trap & roll (upa)", "Heel drag escape"] },
      { name: "Turtle (bottom)", techniques: ["Sit-out", "Granby roll", "Single leg counter", "Guard recovery"] },
      { name: "Back Taken (defending)", techniques: ["Hand fight", "Shoulder walk escape", "Boot scoot", "Turn to guard"] },
      { name: "Bottom North-South", techniques: ["Frame and spin", "Kimura counter", "Guard recovery"] },
      { name: "Bottom Knee on Belly", techniques: ["Frame and shrimp", "Far hip push escape", "Guard recovery"] },
      { name: "Flattened / Smashed", techniques: ["Frame creation", "Reguard attempt", "Underhook recovery"] },
    ],
  },
  {
    id: "leg-entanglement",
    label: "Leg Entanglements",
    color: "#F97316",
    icon: "🦵",
    positions: [
      { name: "Single Leg X / Ashi Garami", techniques: ["Straight ankle lock", "Inside heel hook", "Toe hold", "Transition to inside sankaku", "Sweep"] },
      { name: "Straight Ashi Garami", techniques: ["Straight ankle lock", "Toe hold", "Transition to inside sankaku", "Transition to outside ashi"] },
      { name: "Outside Ashi Garami", techniques: ["Kneebar", "Outside heel hook", "Toe hold", "Transition to outside sankaku"] },
      { name: "Inside Sankaku (Honeyhole/Saddle)", techniques: ["Inside heel hook", "Toe hold", "Calf slicer", "Transition to backside 50/50"] },
      { name: "Outside Sankaku (411)", techniques: ["Outside heel hook", "Kneebar", "Toe hold", "Transition to cross ashi"] },
      { name: "Cross Ashi Garami", techniques: ["Inside heel hook", "Outside heel hook", "Kneebar", "Transition to inside sankaku"] },
      { name: "50/50", techniques: ["Heel hook", "Kneebar", "Toe hold", "Sweep to top 50/50", "Transition to backside 50/50"] },
      { name: "Backside 50/50", techniques: ["Heel hook", "Calf slicer", "Back take", "Transition to inside sankaku"] },
    ],
  },
  {
    id: "scrambles",
    label: "Scrambles & Transitions",
    color: "#8B5CF6",
    icon: "🔄",
    positions: [
      { name: "Turtle (top — attacking)", techniques: ["Clock choke", "Seatbelt → back take", "Truck entry", "Snap down to front headlock"] },
      { name: "Front Headlock / Guillotine", techniques: ["Guillotine choke", "D'Arce choke", "Anaconda choke", "Snap to front headlock", "Go-behind"] },
      { name: "Dogfight / Underhook Battle", techniques: ["Single leg finish", "Back take", "Front headlock", "Sweep"] },
      { name: "Wrestling Scramble", techniques: ["Re-shot", "Sprawl", "Go-behind", "Front headlock"] },
      { name: "Guard Recovery (in progress)", techniques: ["Shrimp to guard", "Granby roll", "Inversion", "Frame and reguard"] },
      { name: "Pass in Progress", techniques: ["Knee slide", "Leg drag", "Smash pass", "Toreando"] },
      { name: "Sweep in Progress", techniques: ["Hook sweep", "Scissor sweep", "Pendulum sweep", "Technical standup"] },
      { name: "Back Exposure (partially turned)", techniques: ["Seatbelt → back take", "Harness control", "Truck entry", "Guard recovery"] },
      { name: "Submission Defence (escaping)", techniques: ["Hand fight", "Hitchhiker escape", "Stack defence", "Posture break"] },
    ],
  },
];

const totalPositions = taxonomy.reduce((a, c) => a + c.positions.length, 0);
const totalTechniques = taxonomy.reduce(
  (a, c) => a + c.positions.reduce((b, p) => b + p.techniques.length, 0),
  0
);

function CategoryCard({ category, isOpen, onToggle }) {
  return (
    <div
      style={{
        border: `1px solid ${category.color}33`,
        borderRadius: 10,
        marginBottom: 10,
        background: isOpen ? `${category.color}08` : "#111214",
        overflow: "hidden",
        transition: "all 0.2s ease",
      }}
    >
      <button
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 16px",
          border: "none",
          background: "none",
          cursor: "pointer",
          color: "#E5E7EB",
          fontFamily: "'Barlow Condensed', sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>{category.icon}</span>
          <span
            style={{
              fontSize: 17,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: category.color,
            }}
          >
            {category.label}
          </span>
          <span
            style={{
              fontSize: 12,
              color: "#6B7280",
              background: "#1F2937",
              padding: "2px 8px",
              borderRadius: 20,
              fontFamily: "'IBM Plex Mono', monospace",
            }}
          >
            {category.positions.length} positions
          </span>
        </div>
        <span
          style={{
            color: "#6B7280",
            fontSize: 18,
            transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.2s ease",
          }}
        >
          ▸
        </span>
      </button>
      {isOpen && (
        <div style={{ padding: "0 16px 14px 16px" }}>
          {category.positions.map((pos, i) => (
            <PositionRow key={i} position={pos} color={category.color} />
          ))}
        </div>
      )}
    </div>
  );
}

function PositionRow({ position, color }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      style={{
        borderLeft: `2px solid ${color}44`,
        marginLeft: 10,
        marginBottom: 4,
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          background: "none",
          border: "none",
          color: "#D1D5DB",
          cursor: "pointer",
          padding: "6px 12px",
          width: "100%",
          textAlign: "left",
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontFamily: "'Barlow', sans-serif",
          fontSize: 14,
        }}
      >
        <span
          style={{
            color: color,
            fontSize: 10,
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.15s ease",
            display: "inline-block",
          }}
        >
          ▶
        </span>
        <span style={{ fontWeight: 600 }}>{position.name}</span>
        <span
          style={{
            fontSize: 11,
            color: "#4B5563",
            fontFamily: "'IBM Plex Mono', monospace",
          }}
        >
          {position.techniques.length} techniques
        </span>
      </button>
      {open && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            padding: "4px 12px 10px 32px",
          }}
        >
          {position.techniques.map((t, i) => (
            <span
              key={i}
              style={{
                background: `${color}18`,
                border: `1px solid ${color}30`,
                color: "#D1D5DB",
                padding: "3px 10px",
                borderRadius: 20,
                fontSize: 12,
                fontFamily: "'Barlow', sans-serif",
                whiteSpace: "nowrap",
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BJJTaxonomy() {
  const [openCats, setOpenCats] = useState(new Set());

  const toggle = (id) => {
    setOpenCats((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const expandAll = () => setOpenCats(new Set(taxonomy.map((c) => c.id)));
  const collapseAll = () => setOpenCats(new Set());

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0B0C0F",
        color: "#E5E7EB",
        fontFamily: "'Barlow', sans-serif",
        padding: "32px 20px",
        maxWidth: 700,
        margin: "0 auto",
      }}
    >
      <link
        href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;700&family=Barlow:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
        rel="stylesheet"
      />
      <div style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontSize: 28,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "#F9FAFB",
            margin: 0,
            lineHeight: 1.2,
          }}
        >
          BJJ Position Taxonomy
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "#6B7280",
            margin: "6px 0 0 0",
            fontFamily: "'IBM Plex Mono', monospace",
          }}
        >
          AI Label Set for Rolling Analysis
        </p>

        <div
          style={{
            display: "flex",
            gap: 12,
            marginTop: 16,
            flexWrap: "wrap",
          }}
        >
          {[
            { label: "Categories", value: taxonomy.length, col: "#8B5CF6" },
            { label: "Positions", value: totalPositions, col: "#3B82F6" },
            { label: "Techniques", value: totalTechniques, col: "#10B981" },
          ].map((s) => (
            <div
              key={s.label}
              style={{
                background: "#161821",
                border: "1px solid #1F2937",
                borderRadius: 8,
                padding: "10px 16px",
                flex: "1 1 100px",
                minWidth: 100,
              }}
            >
              <div
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: s.col,
                  fontFamily: "'Barlow Condensed', sans-serif",
                }}
              >
                {s.value}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: "#6B7280",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
              >
                {s.label}
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button
            onClick={expandAll}
            style={{
              background: "#1F2937",
              border: "1px solid #374151",
              color: "#9CA3AF",
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 12,
              cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
            }}
          >
            Expand all
          </button>
          <button
            onClick={collapseAll}
            style={{
              background: "#1F2937",
              border: "1px solid #374151",
              color: "#9CA3AF",
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 12,
              cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
            }}
          >
            Collapse all
          </button>
        </div>
      </div>

      {taxonomy.map((cat) => (
        <CategoryCard
          key={cat.id}
          category={cat}
          isOpen={openCats.has(cat.id)}
          onToggle={() => toggle(cat.id)}
        />
      ))}

      <div
        style={{
          marginTop: 24,
          padding: 16,
          background: "#161821",
          border: "1px solid #1F2937",
          borderRadius: 8,
          fontSize: 12,
          color: "#6B7280",
          fontFamily: "'IBM Plex Mono', monospace",
          lineHeight: 1.7,
        }}
      >
        <strong style={{ color: "#9CA3AF" }}>Labelling notes:</strong>
        <br />
        → Layer 1 — classify the <strong style={{ color: "#9CA3AF" }}>category</strong> (highest accuracy, easiest)
        <br />
        → Layer 2 — classify the <strong style={{ color: "#9CA3AF" }}>specific position</strong> within the category
        <br />
        → Layer 3 — detect the <strong style={{ color: "#9CA3AF" }}>active technique</strong> being attempted or executed
        <br />
        → Each frame should carry labels for both players (Player A position + Player B position)
        <br />
        → Transitions between positions are as valuable as the positions themselves
      </div>
    </div>
  );
}
