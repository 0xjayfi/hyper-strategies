import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts';
import { COLORS } from '../../lib/constants';

interface ScoreBreakdown {
  roi: number;
  sharpe: number;
  win_rate: number;
  consistency: number;
  smart_money: number;
  risk_mgmt: number;
}

interface ScoreRadarChartProps {
  scoreBreakdown: ScoreBreakdown | null;
}

const AXES = [
  { key: 'roi', label: 'ROI' },
  { key: 'sharpe', label: 'Sharpe' },
  { key: 'win_rate', label: 'Win Rate' },
  { key: 'consistency', label: 'Consistency' },
  { key: 'smart_money', label: 'Smart Money' },
  { key: 'risk_mgmt', label: 'Risk Mgmt' },
] as const;

export function ScoreRadarChart({ scoreBreakdown }: ScoreRadarChartProps) {
  if (!scoreBreakdown) return null;

  const data = AXES.map(({ key, label }) => ({
    axis: label,
    value: scoreBreakdown[key],
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wider">
        Score Breakdown
      </h3>
      <ResponsiveContainer width="100%" height={250}>
        <RadarChart data={data}>
          <PolarGrid stroke={COLORS.border} />
          <PolarAngleAxis
            dataKey="axis"
            tick={{ fill: COLORS.textPrimary, fontSize: 11 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 1]}
            tick={false}
            axisLine={false}
          />
          <Radar
            dataKey="value"
            stroke={COLORS.accent}
            fill={COLORS.accent}
            fillOpacity={0.3}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
