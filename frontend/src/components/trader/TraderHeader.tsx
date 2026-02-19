import { useState } from 'react';
import { Copy, Check, AlertTriangle, Clock } from 'lucide-react';
import type { TraderDetailResponse } from '../../api/types';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { truncateAddress, formatUsd } from '../../lib/utils';

interface TraderHeaderProps {
  trader: TraderDetailResponse;
}

export function TraderHeader({ trader }: TraderHeaderProps) {
  const [copied, setCopied] = useState(false);

  function copyAddress() {
    navigator.clipboard.writeText(trader.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-3">
      {trader.is_blacklisted && (
        <div className="flex items-center gap-2 rounded-lg border border-red/30 bg-red/10 px-4 py-2.5">
          <AlertTriangle className="h-4 w-4 text-red shrink-0" />
          <span className="text-sm text-red font-medium">This trader is blacklisted</span>
        </div>
      )}

      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            {trader.label && (
              <h2 className="text-xl font-semibold text-text-primary">{trader.label}</h2>
            )}
            <div className="flex items-center gap-2">
              <span className="font-mono-nums text-sm text-text-muted" title={trader.address}>
                {truncateAddress(trader.address)}
              </span>
              <button
                onClick={copyAddress}
                className="rounded p-1 text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
                title="Copy address"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-green" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {trader.is_smart_money && <SmartMoneyBadge />}
              {trader.trading_style && (
                <span className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium bg-accent/15 text-accent">
                  {trader.trading_style.toUpperCase()}
                </span>
              )}
            </div>
          </div>

          <div className="flex gap-6">
            {trader.account_value_usd != null && (
              <div className="text-right">
                <span className="text-xs text-text-muted">Account Value</span>
                <div className="font-mono-nums text-lg text-text-primary">
                  {formatUsd(trader.account_value_usd, true)}
                </div>
              </div>
            )}
            {trader.allocation_weight != null && (
              <div className="text-right">
                <span className="text-xs text-text-muted">Allocation</span>
                <div className="font-mono-nums text-lg text-accent">
                  {(trader.allocation_weight * 100).toFixed(1)}%
                </div>
              </div>
            )}
          </div>
        </div>

        {trader.last_active && (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-text-muted">
            <Clock className="h-3 w-3" />
            Last active: {new Date(trader.last_active).toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}
