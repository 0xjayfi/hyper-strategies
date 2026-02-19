import { useEffect, useRef, useState, useMemo } from 'react';
import { createChart, type IChartApi, ColorType, CrosshairMode, type ISeriesApi, LineSeries } from 'lightweight-charts';
import type { PnlPoint } from '../../api/types';
import { cn } from '../../lib/utils';

const RANGE_OPTIONS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
] as const;

interface PnlCurveChartProps {
  points: PnlPoint[];
}

export function PnlCurveChart({ points }: PnlCurveChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [range, setRange] = useState<number>(90);

  const filteredPoints = useMemo(() => {
    const cutoff = Date.now() - range * 24 * 60 * 60 * 1000;
    return points
      .filter((p) => new Date(p.timestamp).getTime() >= cutoff)
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [points, range]);

  const chartData = useMemo(
    () =>
      filteredPoints.map((p) => ({
        time: (Math.floor(new Date(p.timestamp).getTime() / 1000)) as import('lightweight-charts').UTCTimestamp,
        value: p.cumulative_pnl,
      })),
    [filteredPoints]
  );

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b949e',
        fontFamily: "'SF Mono', 'Fira Code', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#30363d' },
        horzLines: { color: '#30363d' },
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
      },
      rightPriceScale: {
        borderColor: '#30363d',
      },
      timeScale: {
        borderColor: '#30363d',
        timeVisible: false,
      },
    });

    const series = chart.addSeries(LineSeries, {
      color: '#58a6ff',
      lineWidth: 2,
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => {
          if (Math.abs(price) >= 1_000_000) return `$${(price / 1_000_000).toFixed(2)}M`;
          if (Math.abs(price) >= 1_000) return `$${(price / 1_000).toFixed(1)}K`;
          return `$${price.toFixed(0)}`;
        },
      },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (seriesRef.current && chartData.length > 0) {
      seriesRef.current.setData(chartData);
      chartRef.current?.timeScale().fitContent();
    }
  }, [chartData]);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">Cumulative PnL</h3>
        <div className="flex rounded-md border border-border">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              onClick={() => setRange(opt.days)}
              className={cn(
                'px-3 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md',
                range === opt.days
                  ? 'bg-accent text-white'
                  : 'text-text-muted hover:bg-surface hover:text-text-primary'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartContainerRef} style={{ height: 300 }} />
    </div>
  );
}
