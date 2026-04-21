/**
 * Pure helpers for the graph page — no DOM access, no Cytoscape import.
 * Tested in isolation; consumed by GraphCluster.svelte for Cytoscape integration.
 */
import type { GraphPaths, GraphTaxonomy, PathPoint } from './types';

export type Point2D = { x: number; y: number };

export type CyNode = {
  data: {
    id: string;
    parent?: string;
    label?: string;
    tint?: string;
    isCategory?: boolean;
  };
};

export type CyEdge = {
  data: { id: string; source: string; target: string };
  classes?: string;
};

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Build Cytoscape-shaped nodes + edges from the taxonomy and (optionally) per-roll paths.
 *
 * Output shape:
 *   - One compound parent node per category, id `cat:<category_id>`, data.isCategory=true, data.tint=<hex>.
 *   - One position node per taxonomy position, parented by `cat:<category>`, data.label=<name>.
 *   - One edge per taxonomy transition, class `taxonomy`.
 *   - For each non-empty player path: one overlay edge per consecutive pair, class `path-greig` or `path-anthony`.
 */
export function buildCytoscapeElements(
  taxonomy: GraphTaxonomy,
  paths: GraphPaths,
  maxTimeS?: number
): { nodes: CyNode[]; edges: CyEdge[] } {
  const nodes: CyNode[] = [];
  const edges: CyEdge[] = [];

  for (const cat of taxonomy.categories) {
    nodes.push({
      data: {
        id: `cat:${cat.id}`,
        label: cat.label,
        tint: cat.tint,
        isCategory: true
      }
    });
  }

  for (const pos of taxonomy.positions) {
    nodes.push({
      data: {
        id: pos.id,
        parent: `cat:${pos.category}`,
        label: pos.name
      }
    });
  }

  for (const tr of taxonomy.transitions) {
    edges.push({
      data: {
        id: `tax:${tr.from}->${tr.to}`,
        source: tr.from,
        target: tr.to
      },
      classes: 'taxonomy'
    });
  }

  for (const [who, allPoints] of [
    ['greig', paths.paths.greig],
    ['anthony', paths.paths.anthony]
  ] as const) {
    const points =
      maxTimeS === undefined
        ? allPoints
        : allPoints.filter((p) => p.timestamp_s <= maxTimeS);
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      edges.push({
        data: {
          id: `path:${who}:${prev.moment_id}->${curr.moment_id}`,
          source: prev.position_id,
          target: curr.position_id
        },
        classes: `path-${who}`
      });
    }
  }

  return { nodes, edges };
}

/**
 * Compute the position of a player's path-head marker at `scrubTimeS`.
 *
 * Returns null when:
 *  - path is empty, OR
 *  - scrubTimeS is before the first analysed point, OR
 *  - a referenced position_id isn't in nodeLookup (missing node).
 *
 * Otherwise linearly interpolates between the two bracketing path points,
 * or rests on the last point if scrubTimeS is past the final timestamp.
 */
export function headPositionAt(
  path: PathPoint[],
  scrubTimeS: number,
  nodeLookup: Map<string, Point2D>
): Point2D | null {
  if (path.length === 0) return null;
  if (scrubTimeS < path[0].timestamp_s) return null;

  // Find the last point where timestamp_s <= scrubTimeS.
  let prevIdx = 0;
  for (let i = 0; i < path.length; i++) {
    if (path[i].timestamp_s <= scrubTimeS) {
      prevIdx = i;
    } else {
      break;
    }
  }

  const prev = path[prevIdx];
  const next = path[prevIdx + 1];

  const prevPos = nodeLookup.get(prev.position_id);
  if (prevPos === undefined) return null;

  if (next === undefined) {
    return { x: prevPos.x, y: prevPos.y };
  }

  const nextPos = nodeLookup.get(next.position_id);
  if (nextPos === undefined) return null;

  const span = next.timestamp_s - prev.timestamp_s;
  const t = span === 0 ? 0 : (scrubTimeS - prev.timestamp_s) / span;
  return {
    x: lerp(prevPos.x, nextPos.x, t),
    y: lerp(prevPos.y, nextPos.y, t)
  };
}

/**
 * Return the position_ids each player is at at `scrubTimeS` (the last point
 * where timestamp_s <= scrubTimeS). Null per player if their path has no
 * points at or before scrubTimeS.
 */
export function currentPositionIds(
  paths: GraphPaths,
  scrubTimeS: number
): { greig: string | null; anthony: string | null } {
  function last(pts: Array<{ timestamp_s: number; position_id: string }>): string | null {
    let id: string | null = null;
    for (const p of pts) {
      if (p.timestamp_s <= scrubTimeS) id = p.position_id;
      else break;
    }
    return id;
  }
  return {
    greig: last(paths.paths.greig),
    anthony: last(paths.paths.anthony)
  };
}
