import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import type { LeaderboardTrader } from '../../api/types';
import { formatPct, truncateAddress } from '../../lib/utils';
import { PnlDisplay } from '../shared/PnlDisplay';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { FilterBadges } from './FilterBadges';

const columnHelper = createColumnHelper<LeaderboardTrader>();

const columns = [
  columnHelper.accessor('rank', {
    header: '#',
    cell: (info) => <span className="text-text-muted">{info.getValue()}</span>,
    size: 50,
  }),
  columnHelper.accessor('address', {
    header: 'Trader',
    cell: (info) => {
      const row = info.row.original;
      return (
        <div className="flex flex-col gap-0.5">
          {row.label && (
            <span className="text-xs text-text-primary">{row.label}</span>
          )}
          <div className="flex items-center gap-1.5">
            <span className="font-mono-nums text-xs text-text-muted">
              {truncateAddress(info.getValue())}
            </span>
            {row.is_smart_money && <SmartMoneyBadge />}
          </div>
        </div>
      );
    },
    size: 200,
    enableSorting: false,
  }),
  columnHelper.accessor('pnl_usd', {
    header: 'PnL',
    cell: (info) => <PnlDisplay value={info.getValue()} compact />,
    size: 110,
  }),
  columnHelper.accessor('roi_pct', {
    header: 'ROI%',
    cell: (info) => {
      const val = info.getValue();
      return (
        <span className={`font-mono-nums ${val >= 0 ? 'text-green' : 'text-red'}`}>
          {formatPct(val)}
        </span>
      );
    },
    size: 90,
  }),
  columnHelper.accessor('win_rate', {
    header: 'Win Rate',
    cell: (info) => {
      const val = info.getValue();
      return (
        <span className="font-mono-nums text-text-primary">
          {val != null ? `${(val * 100).toFixed(1)}%` : '—'}
        </span>
      );
    },
    size: 90,
  }),
  columnHelper.accessor('profit_factor', {
    header: 'Profit Factor',
    cell: (info) => {
      const val = info.getValue();
      return (
        <span className="font-mono-nums text-text-primary">
          {val != null ? val.toFixed(2) : '—'}
        </span>
      );
    },
    size: 100,
  }),
  columnHelper.accessor('num_trades', {
    header: 'Trades',
    cell: (info) => (
      <span className="font-mono-nums text-text-primary">{info.getValue()}</span>
    ),
    size: 70,
  }),
  columnHelper.accessor('anti_luck_status', {
    header: 'Anti-Luck',
    cell: (info) => <FilterBadges status={info.getValue()} />,
    size: 80,
    enableSorting: false,
  }),
  columnHelper.accessor('score', {
    header: 'Score',
    cell: (info) => {
      const val = info.getValue();
      if (val == null) return <span className="text-text-muted">—</span>;
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.min(val * 100, 100)}%` }}
            />
          </div>
          <span className="font-mono-nums text-xs text-text-primary">
            {val.toFixed(2)}
          </span>
        </div>
      );
    },
    size: 130,
  }),
  columnHelper.accessor('allocation_weight', {
    header: 'Weight',
    cell: (info) => {
      const val = info.getValue();
      return (
        <span className="font-mono-nums text-text-primary">
          {val != null ? `${(val * 100).toFixed(1)}%` : '—'}
        </span>
      );
    },
    size: 80,
  }),
];

interface LeaderboardTableProps {
  data: LeaderboardTrader[];
  onSelectTrader?: (address: string) => void;
}

export function LeaderboardTable({ data, onSelectTrader }: LeaderboardTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const navigate = useNavigate();

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-border bg-card">
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-3 py-2.5 text-left text-xs font-medium text-text-muted"
                  style={{ width: header.getSize() }}
                >
                  {header.isPlaceholder ? null : (
                    <button
                      className="flex items-center gap-1"
                      onClick={header.column.getToggleSortingHandler()}
                      disabled={!header.column.getCanSort()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getCanSort() && (
                        <span className="text-text-muted">
                          {header.column.getIsSorted() === 'asc' ? (
                            <ChevronUp className="h-3 w-3" />
                          ) : header.column.getIsSorted() === 'desc' ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronsUpDown className="h-3 w-3 opacity-30" />
                          )}
                        </span>
                      )}
                    </button>
                  )}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="cursor-pointer border-b border-border transition-colors hover:bg-card/50"
              onClick={() => {
                const addr = row.original.address;
                onSelectTrader?.(addr);
                navigate(`/traders/${addr}`);
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2.5">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
