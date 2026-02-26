import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Info } from 'lucide-react';
import { useAllocationHistory } from '../../api/hooks';

interface AllocationHistoryProps {
  address: string;
  currentWeight: number | null;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

export function AllocationHistory({ address, currentWeight }: AllocationHistoryProps) {
  const { data: historyData } = useAllocationHistory(30);

  if (currentWeight == null) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-medium text-text-primary">Allocation History</h3>
        <div className="flex flex-col items-center justify-center gap-2 py-10">
          <Info className="h-5 w-5 text-text-muted" />
          <p className="text-xs text-text-muted">Allocation history not available</p>
        </div>
      </div>
    );
  }

  // Extract this trader's weight from each snapshot
  const snapshots = historyData?.snapshots ?? [];
  const data = snapshots
    .map((s) => {
      const entry = s.allocations.find((a) => a.address === address);
      return {
        label: formatTime(s.computed_at),
        weight: entry ? +(entry.final_weight * 100).toFixed(1) : 0,
      };
    })
    .filter((d) => d.weight > 0);

  // If no historical points, show the current weight as a single point
  const hasHistory = data.length > 1;
  const chartData = hasHistory
    ? data
    : [{ label: 'Current', weight: +(currentWeight * 100).toFixed(1) }];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-medium text-text-primary">Allocation History</h3>
      <div className="mb-2 text-center">
        <span className="font-mono-nums text-2xl font-semibold text-accent">
          {(currentWeight * 100).toFixed(1)}%
        </span>
        <p className="text-xs text-text-muted mt-1">Current Allocation Weight</p>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <defs>
            <linearGradient id="allocGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis hide domain={[0, 'auto']} />
          <Tooltip
            contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#8b949e' }}
            formatter={(value: number | undefined) => [`${(value ?? 0).toFixed(1)}%`, 'Weight']}
          />
          <Area type="monotone" dataKey="weight" stroke="#58a6ff" fill="url(#allocGrad)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
      {!hasHistory && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
          <Info className="h-3 w-3" />
          Weight history will appear after multiple allocation cycles
        </div>
      )}
    </div>
  );
}
