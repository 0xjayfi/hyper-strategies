import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import type { AllocationEntry } from '../../api/types';
import { truncateAddress } from '../../lib/utils';

const PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#d2a8ff',
  '#f0883e', '#56d4dd', '#e3b341', '#8b949e',
];

interface WeightsDonutProps {
  allocations: AllocationEntry[];
}

export function WeightsDonut({ allocations }: WeightsDonutProps) {
  const data = allocations.map((a, i) => ({
    name: a.label || truncateAddress(a.address),
    value: a.weight,
    fill: PALETTE[i % PALETTE.length],
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
        Allocation Weights
      </h3>
      <div className="flex flex-col items-center">
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={100}
              dataKey="value"
              stroke="none"
            >
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.fill} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6 }}
              itemStyle={{ color: '#e6edf3' }}
              formatter={(value) => `${(Number(value) * 100).toFixed(1)}%`}
            />
            <text
              x="50%"
              y="50%"
              textAnchor="middle"
              dominantBaseline="central"
              fill="#e6edf3"
              fontSize={14}
              fontWeight={600}
            >
              {allocations.length} traders
            </text>
          </PieChart>
        </ResponsiveContainer>
        <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1">
          {data.map((entry, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-full" style={{ background: entry.fill }} />
              <span>{entry.name}</span>
              <span className="font-mono text-text-primary">
                {(entry.value * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
