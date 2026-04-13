import { useState, useRef, useEffect } from "react";

const CATEGORIES = {
  standing: { color: "#8B8FA3", label: "Standing" },
  guard: { color: "#4A90D9", label: "Guard (Bottom)" },
  guardTop: { color: "#D4A843", label: "Guard (Top)" },
  dominant: { color: "#34C759", label: "Dominant (Top)" },
  inferior: { color: "#E85D4A", label: "Inferior (Bottom)" },
  scramble: { color: "#AF52DE", label: "Scramble / Neutral" },
};

const nodes = [
  { id: "standing", label: "Standing", cat: "standing", x: 400, y: 40, yt: "https://www.youtube.com/watch?v=VYq3yASQ3xA", ytTitle: "BJJ Takedowns for Beginners", techniques: ["Single leg", "Double leg", "Arm drag", "Guard pull"] },
  { id: "clinch", label: "Clinch", cat: "standing", x: 240, y: 100, yt: "https://www.youtube.com/watch?v=3_OvFnmfa18", ytTitle: "Clinch Work for BJJ", techniques: ["Inside trip", "Body lock TD", "Snap down"] },
  { id: "closedGuard", label: "Closed\nGuard", cat: "guard", x: 140, y: 230, yt: "https://www.youtube.com/watch?v=hUP_cSjOGRI", ytTitle: "Closed Guard Fundamentals – Roger Gracie", techniques: ["Armbar", "Triangle", "Kimura", "Hip bump sweep", "Omoplata"] },
  { id: "halfGuard", label: "Half\nGuard", cat: "guard", x: 300, y: 310, yt: "https://www.youtube.com/watch?v=A1yMhKVRMSs", ytTitle: "Half Guard Basics – Lachlan Giles", techniques: ["Underhook sweep", "Lockdown", "Dogfight", "Electric chair", "Knee shield"] },
  { id: "openGuard", label: "Open\nGuard", cat: "guard", x: 100, y: 370, yt: "https://www.youtube.com/watch?v=UTaZzbHMr-s", ytTitle: "Open Guard System for Beginners", techniques: ["DLR sweep", "Spider guard", "Butterfly hook sweep", "Collar drag"] },
  { id: "butterfly", label: "Butterfly\nGuard", cat: "guard", x: 60, y: 280, yt: "https://www.youtube.com/watch?v=Tz0JfjGeerQ", ytTitle: "Butterfly Guard – Marcelo Garcia", techniques: ["Hook sweep", "Guillotine", "Arm drag", "X-guard entry"] },
  { id: "dlr", label: "De La\nRiva", cat: "guard", x: 50, y: 440, yt: "https://www.youtube.com/watch?v=xRBPIYTJwNk", ytTitle: "DLR Guard Complete Guide", techniques: ["Berimbolo", "Back take", "Kiss of the dragon", "Sweep"] },
  { id: "singleLegX", label: "SLX /\nAshi", cat: "scramble", x: 140, y: 520, yt: "https://www.youtube.com/watch?v=j3LslfGWN10", ytTitle: "Ashi Garami / SLX System – Craig Jones", techniques: ["Straight ankle lock", "Inside heel hook", "Outside heel hook", "Toe hold"] },
  { id: "fiftyFifty", label: "50/50", cat: "scramble", x: 260, y: 530, yt: "https://www.youtube.com/watch?v=1fPkOJ-mFAQ", ytTitle: "50/50 Position Explained", techniques: ["Heel hook", "Kneebar", "Toe hold", "Sweep"] },
  { id: "closedGuardTop", label: "In Closed\nGuard (Top)", cat: "guardTop", x: 300, y: 190, yt: "https://www.youtube.com/watch?v=iEU_jHg2W4E", ytTitle: "How to Pass Closed Guard", techniques: ["Guard break", "Stack pass", "Standing pass"] },
  { id: "halfGuardTop", label: "Half Guard\n(Top)", cat: "guardTop", x: 450, y: 280, yt: "https://www.youtube.com/watch?v=zIH3gKnj2dE", ytTitle: "Passing Half Guard – Andre Galvao", techniques: ["Knee slide", "Smash pass", "Crossface", "Underhook denial"] },
  { id: "hq", label: "HQ /\nPassing", cat: "guardTop", x: 510, y: 190, yt: "https://www.youtube.com/watch?v=quSDqYbPoto", ytTitle: "Headquarters Passing Position", techniques: ["Knee slide", "Leg weave", "Smash pass", "Toreando"] },
  { id: "sideControl", label: "Side\nControl", cat: "dominant", x: 580, y: 310, yt: "https://www.youtube.com/watch?v=cuXq-k__9lQ", ytTitle: "Side Control Masterclass – John Danaher", techniques: ["Americana", "Kimura", "Arm triangle", "Baseball choke"] },
  { id: "mount", label: "Mount", cat: "dominant", x: 660, y: 220, yt: "https://www.youtube.com/watch?v=_MPwnl9AzjE", ytTitle: "Full Mount Attacks – Roger Gracie", techniques: ["Armbar", "Cross collar choke", "Ezekiel", "S-mount triangle"] },
  { id: "kneeOnBelly", label: "Knee on\nBelly", cat: "dominant", x: 700, y: 130, yt: "https://www.youtube.com/watch?v=NnDCiHnBnxo", ytTitle: "Knee on Belly Pressure & Attacks", techniques: ["Armbar", "Baseball choke", "Far side armbar", "Transition to mount"] },
  { id: "backMount", label: "Back\nMount", cat: "dominant", x: 740, y: 330, yt: "https://www.youtube.com/watch?v=2o_kV5DLZ5o", ytTitle: "Back Control & RNC – Danaher", techniques: ["Rear naked choke", "Bow & arrow", "Short choke", "Armbar"] },
  { id: "northSouth", label: "North\nSouth", cat: "dominant", x: 530, y: 400, yt: "https://www.youtube.com/watch?v=u68f9MWJmBc", ytTitle: "North-South Choke – Marcelo Garcia", techniques: ["NS choke", "Kimura", "Armbar", "Transition to side control"] },
  { id: "turtle", label: "Turtle\n(Top)", cat: "scramble", x: 620, y: 440, yt: "https://www.youtube.com/watch?v=_gNBsJO。fCb4", ytTitle: "Attacking Turtle – BJJ Fanatics", techniques: ["Clock choke", "Seatbelt → back take", "Truck entry", "Snap to front head"] },
  { id: "frontHead", label: "Front\nHeadlock", cat: "scramble", x: 400, y: 460, yt: "https://www.youtube.com/watch?v=FFBiGNPhcTM", ytTitle: "Front Headlock System – D'Arce & Guillotine", techniques: ["Guillotine", "D'Arce", "Anaconda", "Go-behind to back take"] },
  { id: "bottomSide", label: "Bottom\nSide Ctrl", cat: "inferior", x: 450, y: 380, yt: "https://www.youtube.com/watch?v=V7vmzcc3ldA", ytTitle: "Side Control Escapes – Priit Mihkelson", techniques: ["Frame → reguard", "Underhook escape", "Ghost escape", "Shrimp to half guard"] },
  { id: "bottomMount", label: "Bottom\nMount", cat: "inferior", x: 660, y: 380, yt: "https://www.youtube.com/watch?v=WoSwnUISfD4", ytTitle: "Mount Escape Fundamentals", techniques: ["Trap & roll (upa)", "Elbow-knee escape", "Heel drag"] },
  { id: "turtleBottom", label: "Turtle\n(Bottom)", cat: "inferior", x: 500, y: 500, yt: "https://www.youtube.com/watch?v=rEas-WkEJFU", ytTitle: "Turtle Escapes & Guard Recovery", techniques: ["Sit-out", "Granby roll", "Guard recovery", "Single leg counter"] },
  { id: "backTaken", label: "Back\nTaken", cat: "inferior", x: 740, y: 460, yt: "https://www.youtube.com/watch?v=aRwJE6-Bneo", ytTitle: "Back Escape – Danaher", techniques: ["Hand fight", "Shoulder walk", "Turn into guard"] },
];

const edges = [
  ["standing", "clinch"],
  ["standing", "closedGuard"], ["standing", "openGuard"],
  ["standing", "closedGuardTop"], ["standing", "hq"],
  ["clinch", "closedGuard"], ["clinch", "halfGuard"], ["clinch", "sideControl"],
  ["closedGuard", "closedGuardTop"],
  ["closedGuard", "halfGuard"], ["closedGuard", "openGuard"], ["closedGuard", "mount"],
  ["closedGuardTop", "halfGuardTop"], ["closedGuardTop", "hq"], ["closedGuardTop", "sideControl"],
  ["openGuard", "butterfly"], ["openGuard", "dlr"], ["openGuard", "hq"],
  ["butterfly", "singleLegX"], ["butterfly", "closedGuard"], ["butterfly", "backMount"],
  ["dlr", "singleLegX"], ["dlr", "backMount"], ["dlr", "fiftyFifty"],
  ["singleLegX", "fiftyFifty"],
  ["halfGuard", "halfGuardTop"], ["halfGuard", "closedGuard"], ["halfGuard", "sideControl"],
  ["halfGuardTop", "sideControl"], ["halfGuardTop", "mount"], ["halfGuardTop", "kneeOnBelly"],
  ["hq", "sideControl"], ["hq", "halfGuardTop"], ["hq", "kneeOnBelly"],
  ["sideControl", "mount"], ["sideControl", "kneeOnBelly"], ["sideControl", "northSouth"], ["sideControl", "backMount"],
  ["sideControl", "bottomSide"],
  ["mount", "backMount"], ["mount", "sideControl"],
  ["mount", "bottomMount"],
  ["kneeOnBelly", "mount"], ["kneeOnBelly", "sideControl"],
  ["backMount", "backTaken"],
  ["northSouth", "sideControl"], ["northSouth", "bottomSide"],
  ["bottomSide", "halfGuard"], ["bottomSide", "closedGuard"], ["bottomSide", "turtleBottom"],
  ["bottomMount", "halfGuard"], ["bottomMount", "closedGuard"],
  ["turtleBottom", "turtle"], ["turtleBottom", "halfGuard"],
  ["turtle", "backMount"], ["turtle", "frontHead"],
  ["backTaken", "closedGuard"], ["backTaken", "turtleBottom"],
  ["frontHead", "sideControl"], ["frontHead", "backMount"], ["frontHead", "closedGuard"],
];

function getNodeCenter(node) {
  return { x: node.x, y: node.y };
}

export default function BJJGraph() {
  const [selected, setSelected] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const svgRef = useRef(null);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, startPanX: 0, startPanY: 0 });

  const selectedNode = nodes.find(n => n.id === selected);
  const connectedIds = selected
    ? edges.filter(e => e[0] === selected || e[1] === selected).map(e => e[0] === selected ? e[1] : e[0])
    : [];

  const handlePointerDown = (e) => {
    if (e.target.closest('.node-group')) return;
    dragRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, startPanX: pan.x, startPanY: pan.y };
  };
  const handlePointerMove = (e) => {
    if (!dragRef.current.dragging) return;
    setPan({
      x: dragRef.current.startPanX + (e.clientX - dragRef.current.startX) / scale,
      y: dragRef.current.startPanY + (e.clientY - dragRef.current.startY) / scale,
    });
  };
  const handlePointerUp = () => { dragRef.current.dragging = false; };

  const handleWheel = (e) => {
    e.preventDefault();
    setScale(s => Math.min(2.5, Math.max(0.4, s - e.deltaY * 0.001)));
  };

  useEffect(() => {
    const svg = svgRef.current;
    if (svg) svg.addEventListener('wheel', handleWheel, { passive: false });
    return () => { if (svg) svg.removeEventListener('wheel', handleWheel); };
  }, []);

  return (
    <div style={{
      width: "100%", height: "100vh", background: "#08090C",
      fontFamily: "'Barlow', sans-serif", position: "relative", overflow: "hidden", userSelect: "none"
    }}>
      <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {/* Legend */}
      <div style={{
        position: "absolute", top: 12, left: 12, zIndex: 10,
        background: "#12141AEE", border: "1px solid #1E2030", borderRadius: 10, padding: "12px 14px",
        display: "flex", flexDirection: "column", gap: 6,
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'Barlow Condensed', sans-serif", marginBottom: 2 }}>
          Position Categories
        </div>
        {Object.values(CATEGORIES).map(c => (
          <div key={c.label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: c.color, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "#9CA3AF" }}>{c.label}</span>
          </div>
        ))}
        <div style={{ fontSize: 10, color: "#4B5563", marginTop: 4, fontFamily: "'IBM Plex Mono', monospace" }}>
          Tap node → details + video<br />
          Drag to pan · Pinch to zoom
        </div>
      </div>

      {/* Title */}
      <div style={{
        position: "absolute", top: 12, right: 12, zIndex: 10, textAlign: "right",
      }}>
        <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 20, fontWeight: 700, color: "#F9FAFB", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          BJJ Position Graph
        </div>
        <div style={{ fontSize: 11, color: "#4B5563", fontFamily: "'IBM Plex Mono', monospace" }}>
          {nodes.length} positions · {edges.length} transitions
        </div>
      </div>

      {/* SVG Graph */}
      <svg
        ref={svgRef}
        width="100%" height="100%"
        style={{ cursor: dragRef.current.dragging ? "grabbing" : "grab" }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <g transform={`scale(${scale}) translate(${pan.x}, ${pan.y})`}>
          {/* Edges */}
          {edges.map(([fromId, toId], i) => {
            const from = nodes.find(n => n.id === fromId);
            const to = nodes.find(n => n.id === toId);
            if (!from || !to) return null;
            const isActive = selected && (fromId === selected || toId === selected);
            const activeColor = selected ? CATEGORIES[nodes.find(n => n.id === selected)?.cat]?.color : "#fff";
            return (
              <line key={i}
                x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                stroke={isActive ? activeColor : "#1E2030"}
                strokeWidth={isActive ? 2 : 1}
                opacity={selected ? (isActive ? 0.7 : 0.08) : 0.25}
                style={{ transition: "all 0.3s ease" }}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map(node => {
            const cat = CATEGORIES[node.cat];
            const isSelected = node.id === selected;
            const isConnected = connectedIds.includes(node.id);
            const isHovered = hoveredNode === node.id;
            const dimmed = selected && !isSelected && !isConnected;
            const r = isSelected ? 32 : 26;
            return (
              <g key={node.id} className="node-group"
                style={{ cursor: "pointer", transition: "opacity 0.3s ease" }}
                opacity={dimmed ? 0.15 : 1}
                onClick={() => setSelected(isSelected ? null : node.id)}
                onPointerEnter={() => setHoveredNode(node.id)}
                onPointerLeave={() => setHoveredNode(null)}
              >
                {/* Glow */}
                {(isSelected || isHovered) && (
                  <circle cx={node.x} cy={node.y} r={r + 8} fill={cat.color} opacity={0.15} />
                )}
                {/* Ring */}
                <circle cx={node.x} cy={node.y} r={r}
                  fill={isSelected ? `${cat.color}30` : "#12141A"}
                  stroke={cat.color}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  opacity={isSelected ? 1 : 0.85}
                />
                {/* Label */}
                {node.label.split("\n").map((line, li) => (
                  <text key={li} x={node.x} y={node.y + (li - (node.label.split("\n").length - 1) / 2) * 12}
                    textAnchor="middle" dominantBaseline="central"
                    fill={isSelected ? "#F9FAFB" : "#C9CDD8"}
                    fontSize={9.5} fontWeight={600}
                    fontFamily="'Barlow Condensed', sans-serif"
                    style={{ pointerEvents: "none", letterSpacing: "0.04em" }}
                  >
                    {line}
                  </text>
                ))}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Detail Panel */}
      {selectedNode && (
        <div style={{
          position: "absolute", bottom: 0, left: 0, right: 0, zIndex: 20,
          background: "linear-gradient(to top, #12141AFA 70%, #12141A00)",
          padding: "60px 16px 20px 16px",
        }}>
          <div style={{
            background: "#181B24", border: `1px solid ${CATEGORIES[selectedNode.cat].color}44`,
            borderRadius: 14, padding: 16, maxWidth: 500, margin: "0 auto",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{
                  fontSize: 10, fontWeight: 600, color: CATEGORIES[selectedNode.cat].color,
                  textTransform: "uppercase", letterSpacing: "0.1em",
                  fontFamily: "'IBM Plex Mono', monospace", marginBottom: 4,
                }}>
                  {CATEGORIES[selectedNode.cat].label}
                </div>
                <div style={{
                  fontSize: 20, fontWeight: 700, color: "#F9FAFB",
                  fontFamily: "'Barlow Condensed', sans-serif", textTransform: "uppercase", letterSpacing: "0.05em",
                }}>
                  {selectedNode.label.replace("\n", " ")}
                </div>
              </div>
              <button onClick={() => setSelected(null)} style={{
                background: "#2A2D3A", border: "none", color: "#6B7280",
                borderRadius: 8, width: 30, height: 30, cursor: "pointer",
                fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center",
              }}>✕</button>
            </div>

            {/* Techniques */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
              {selectedNode.techniques.map((t, i) => (
                <span key={i} style={{
                  background: `${CATEGORIES[selectedNode.cat].color}15`,
                  border: `1px solid ${CATEGORIES[selectedNode.cat].color}30`,
                  color: "#C9CDD8", padding: "4px 10px", borderRadius: 20,
                  fontSize: 12, fontFamily: "'Barlow', sans-serif",
                }}>
                  {t}
                </span>
              ))}
            </div>

            {/* Transitions */}
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: "#4B5563", textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 6 }}>
                Transitions to / from
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {connectedIds.map(cid => {
                  const cn = nodes.find(n => n.id === cid);
                  return (
                    <button key={cid} onClick={() => setSelected(cid)} style={{
                      background: `${CATEGORIES[cn.cat].color}18`,
                      border: `1px solid ${CATEGORIES[cn.cat].color}25`,
                      color: CATEGORIES[cn.cat].color,
                      padding: "3px 9px", borderRadius: 14,
                      fontSize: 11, cursor: "pointer", fontFamily: "'Barlow', sans-serif", fontWeight: 500,
                    }}>
                      {cn.label.replace("\n", " ")}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* YouTube Link */}
            <a href={selectedNode.yt} target="_blank" rel="noopener noreferrer" style={{
              display: "flex", alignItems: "center", gap: 10, marginTop: 14,
              background: "#1C1F2B", border: "1px solid #2A2D3A", borderRadius: 10,
              padding: "10px 14px", textDecoration: "none", transition: "border-color 0.2s",
            }}
              onMouseEnter={e => e.currentTarget.style.borderColor = "#E85D4A"}
              onMouseLeave={e => e.currentTarget.style.borderColor = "#2A2D3A"}
            >
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: "#E85D4A22", display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="#E85D4A">
                  <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
                </svg>
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#E5E7EB" }}>{selectedNode.ytTitle}</div>
                <div style={{ fontSize: 10, color: "#6B7280", fontFamily: "'IBM Plex Mono', monospace", marginTop: 2 }}>Watch on YouTube →</div>
              </div>
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
