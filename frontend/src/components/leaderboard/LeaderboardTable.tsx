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
import { truncateAddress } from '../../lib/utils';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { useIsMobile } from '../../hooks/useIsMobile';
import { LeaderboardCardList } from './LeaderboardCard';

const columnHelper = createColumnHelper<LeaderboardTrader>();

/** Mini progress bar cell for score components (0–1 range). */
function MiniScoreBar({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-text-muted">—</span>;
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-10 overflow-hidden rounded-full bg-border">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      <span className="font-mono-nums text-[11px] text-text-primary">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

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
    size: 180,
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
  columnHelper.accessor('score_growth', {
    header: 'Growth',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_drawdown', {
    header: 'Drawdown',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_leverage', {
    header: 'Leverage',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_liq_distance', {
    header: 'Liq Dist',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_diversity', {
    header: 'Diversity',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
  }),
  columnHelper.accessor('score_consistency', {
    header: 'Consistency',
    cell: (info) => <MiniScoreBar value={info.getValue()} />,
    size: 100,
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
  const isMobile = useIsMobile();
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

  if (isMobile) {
    return <LeaderboardCardList data={data} onSelectTrader={onSelectTrader} />;
  }

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
