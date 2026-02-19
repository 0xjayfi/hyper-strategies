import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import type { TokenPerpPosition } from '../../api/types';
import { formatUsd } from '../../lib/utils';

interface PositionRowDetailProps {
  position: TokenPerpPosition;
}

export function PositionRowDetail({ position }: PositionRowDetailProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(position.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Liquidation proximity: how close mark price is to liquidation price
  const liqProximity = position.liquidation_price
    ? Math.abs(position.mark_price - position.liquidation_price) / position.mark_price * 100
    : null;

  // Bar width: closer to liquidation = more filled (cap at 100%)
  const liqBarWidth = liqProximity !== null
    ? Math.max(0, Math.min(100, 100 - liqProximity))
    : 0;

  return (
    <div className="border-t border-border bg-surface px-6 py-4">
      <div className="grid grid-cols-4 gap-6 text-xs">
        <div>
          <span className="text-text-muted">Full Address</span>
          <div className="mt-1 flex items-center gap-1.5">
            <code className="font-mono-nums text-text-primary">{position.address}</code>
            <button onClick={handleCopy} className="text-text-muted hover:text-text-primary">
              {copied ? <Check className="h-3 w-3 text-green" /> : <Copy className="h-3 w-3" />}
            </button>
          </div>
        </div>
        <div>
          <span className="text-text-muted">Funding USD</span>
          <div className="mt-1 font-mono-nums text-text-primary">{formatUsd(position.funding_usd)}</div>
        </div>
        <div>
          <span className="text-text-muted">Leverage Type</span>
          <div className="mt-1 text-text-primary">{position.leverage_type}</div>
        </div>
        <div>
          <span className="text-text-muted">Smart Money Labels</span>
          <div className="mt-1 text-text-primary">
            {position.smart_money_labels.length > 0
              ? position.smart_money_labels.join(', ')
              : 'None'}
          </div>
        </div>
      </div>

      {/* Liquidation Proximity Bar */}
      {position.liquidation_price && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">Liquidation Proximity</span>
            <span className="font-mono-nums text-text-muted">
              {liqProximity?.toFixed(1)}% away
            </span>
          </div>
          <div className="mt-1.5 h-1.5 rounded-full bg-border">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${liqBarWidth}%`,
                backgroundColor: liqBarWidth > 80 ? '#f85149' : liqBarWidth > 50 ? '#d29922' : '#3fb950',
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
