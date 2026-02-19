import type { RiskCaps } from '../../api/types';

function gaugeColor(ratio: number): string {
  if (ratio >= 0.9) return '#f85149';
  if (ratio >= 0.7) return '#e3b341';
  return '#3fb950';
}

function formatCapValue(key: string, value: number): string {
  if (key === 'position_count') return String(value);
  return `${(value * 100).toFixed(1)}%`;
}

interface GaugeBarProps {
  label: string;
  capKey: string;
  current: number;
  max: number;
}

function GaugeBar({ label, capKey, current, max }: GaugeBarProps) {
  const ratio = max > 0 ? current / max : 0;
  const color = gaugeColor(ratio);

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-text-muted">{label}</span>
        <span className="font-mono text-text-primary">
          {formatCapValue(capKey, current)} / {formatCapValue(capKey, max)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-border">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(ratio * 100, 100)}%`, background: color }}
        />
      </div>
    </div>
  );
}

interface RiskGaugesProps {
  riskCaps: RiskCaps;
}

export function RiskGauges({ riskCaps }: RiskGaugesProps) {
  const gauges: { label: string; capKey: keyof RiskCaps }[] = [
    { label: 'Position Count', capKey: 'position_count' },
    { label: 'Max Token Exposure', capKey: 'max_token_exposure' },
    { label: 'Long Directional', capKey: 'directional_long' },
    { label: 'Short Directional', capKey: 'directional_short' },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
        Risk Caps
      </h3>
      <div className="grid grid-cols-2 gap-4">
        {gauges.map(({ label, capKey }) => (
          <GaugeBar
            key={capKey}
            label={label}
            capKey={capKey}
            current={riskCaps[capKey].current}
            max={riskCaps[capKey].max}
          />
        ))}
      </div>
    </div>
  );
}
