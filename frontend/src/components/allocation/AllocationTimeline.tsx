import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { AllocationEntry } from '../../api/types';
import { Info } from 'lucide-react';

const PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#d2a8ff',
  '#f0883e', '#56d4dd', '#e3b341', '#8b949e',
];

interface AllocationTimelineProps {
  allocations: AllocationEntry[];
  computedAt: string | null;
}

export function AllocationTimeline({ allocations, computedAt }: AllocationTimelineProps) {
  const dataPoint: Record<string, number | string> = {
    time: computedAt ?? 'now',
  };
  allocations.forEach((a, i) => {
    dataPoint[a.address.slice(0, 8)] = +(a.weight * 100).toFixed(1);
    // store index for color lookup
    dataPoint[`_idx_${a.address.slice(0, 8)}`] = i;
  });

  const keys = allocations.map((a) => a.address.slice(0, 8));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
        Allocation Over Time
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={[dataPoint]}>
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
      <div className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
        <Info className="h-3 w-3" />
        Historical data will be available after multiple allocation cycles
      </div>
    </div>
  );
}
