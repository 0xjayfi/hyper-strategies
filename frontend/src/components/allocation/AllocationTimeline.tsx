import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { Info } from 'lucide-react';
import { useAllocationHistory } from '../../api/hooks';
import type { AllocationEntry } from '../../api/types';

const PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#d2a8ff',
  '#f0883e', '#56d4dd', '#e3b341', '#8b949e',
];

interface AllocationTimelineProps {
  allocations: AllocationEntry[];
  computedAt: string | null;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export function AllocationTimeline({ allocations, computedAt }: AllocationTimelineProps) {
  const { data: historyData } = useAllocationHistory(30);

  // Build set of all trader addresses across all snapshots (for consistent stacking)
  // Use history if we have multiple snapshots; fall back to current-only
  const snapshots = historyData?.snapshots ?? [];
  const hasHistory = snapshots.length > 1;

  // Collect all unique addresses across all snapshots
  const allAddresses = new Set<string>();
  if (hasHistory) {
    snapshots.forEach((s) =>
      s.allocations.forEach((a) => allAddresses.add(a.address))
    );
  } else {
    allocations.forEach((a) => allAddresses.add(a.address));
  }

  // Build label map: address -> display name (label or truncated address)
  const labelMap = new Map<string, string>();
  if (hasHistory) {
    snapshots.forEach((s) =>
      s.allocations.forEach((a) => {
        if (!labelMap.has(a.address)) {
          labelMap.set(a.address, a.label ?? a.address.slice(0, 8));
        }
      })
    );
  } else {
    allocations.forEach((a) => {
      labelMap.set(a.address, a.label ?? a.address.slice(0, 8));
    });
  }

  // Sorted addresses for consistent colors (by descending latest weight)
  const latestWeights = new Map<string, number>();
  if (hasHistory && snapshots.length > 0) {
    const last = snapshots[snapshots.length - 1];
    last.allocations.forEach((a) => latestWeights.set(a.address, a.final_weight));
  } else {
    allocations.forEach((a) => latestWeights.set(a.address, a.weight));
  }
  const sortedAddresses = [...allAddresses].sort(
    (a, b) => (latestWeights.get(b) ?? 0) - (latestWeights.get(a) ?? 0)
  );

  // Use short keys for the chart (labels, deduplicated)
  const keyFor = (addr: string) => labelMap.get(addr) ?? addr.slice(0, 8);

  // Build chart data
  let chartData: Record<string, number | string>[];
  if (hasHistory) {
    chartData = snapshots.map((s) => {
      const point: Record<string, number | string> = {
        time: formatTime(s.computed_at),
      };
      // Initialize all keys to 0
      sortedAddresses.forEach((addr) => {
        point[keyFor(addr)] = 0;
      });
      // Fill in actual weights
      s.allocations.forEach((a) => {
        point[keyFor(a.address)] = +(a.final_weight * 100).toFixed(1);
      });
      return point;
    });
  } else {
    // Single data point fallback
    const point: Record<string, number | string> = {
      time: computedAt ? formatTime(computedAt) : 'Current',
    };
    allocations.forEach((a) => {
      point[keyFor(a.address)] = +(a.weight * 100).toFixed(1);
    });
    chartData = [point];
  }

  const keys = sortedAddresses.map((addr) => keyFor(addr));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
        Allocation Over Time
      </h3>
      <p className="mb-3 text-xs leading-relaxed text-text-muted">
        This chart tracks how capital allocation shifts across tracked traders over time.
        Weights are recalculated every 6 hours based on updated performance scores.
        Rising allocations indicate improving trader performance, while declining weights
        suggest deteriorating metrics. Use this to understand how the system dynamically
        rebalances exposure.
      </p>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData}>
          <XAxis dataKey="time" tick={{ fill: '#8b949e', fontSize: 10 }} />
          <YAxis tick={{ fill: '#8b949e', fontSize: 10 }} unit="%" />
          <Tooltip
            contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6 }}
            itemStyle={{ color: '#e6edf3' }}
          />
          {keys.map((key, i) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stackId="1"
              fill={PALETTE[i % PALETTE.length]}
              stroke={PALETTE[i % PALETTE.length]}
              fillOpacity={0.6}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      {!hasHistory && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
          <Info className="h-3 w-3" />
          Historical data will be available after multiple allocation cycles
        </div>
      )}
    </div>
  );
}
