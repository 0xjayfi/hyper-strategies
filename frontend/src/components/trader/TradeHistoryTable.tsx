import { useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { ChevronDown, ChevronUp, ChevronsUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import type { TradeItem } from '../../api/types';
import { formatUsd } from '../../lib/utils';
import { TokenBadge } from '../shared/TokenBadge';
import { PnlDisplay } from '../shared/PnlDisplay';
import { useIsMobile } from '../../hooks/useIsMobile';
import { TradeHistoryCardList } from './TradeHistoryCard';

const columnHelper = createColumnHelper<TradeItem>();

const columns = [
  columnHelper.accessor('timestamp', {
    header: 'Timestamp',
    cell: (info) => (
      <span className="font-mono-nums text-xs text-text-muted">
        {new Date(info.getValue()).toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    ),
    size: 140,
  }),
  columnHelper.accessor('token_symbol', {
    header: 'Token',
    cell: (info) => <TokenBadge token={info.getValue()} />,
    size: 80,
    enableSorting: false,
  }),
  columnHelper.accessor('action', {
    header: 'Action',
    cell: (info) => (
      <span className="text-xs font-medium text-text-primary">{info.getValue()}</span>
    ),
    size: 80,
    enableSorting: false,
  }),
  columnHelper.accessor('side', {
    header: 'Side',
    cell: (info) => {
      const val = info.getValue();
      if (!val) return <span className="text-text-muted">-</span>;
      return (
        <span
          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${
            val === 'Long' ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
          }`}
        >
          {val}
        </span>
      );
    },
    size: 70,
    enableSorting: false,
  }),
  columnHelper.accessor('value_usd', {
    header: 'Size USD',
    cell: (info) => (
      <span className="font-mono-nums text-text-primary">{formatUsd(info.getValue(), true)}</span>
    ),
    size: 100,
  }),
  columnHelper.accessor('price', {
    header: 'Price',
    cell: (info) => (
      <span className="font-mono-nums text-text-primary">
        ${info.getValue().toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
    ),
    size: 100,
  }),
  columnHelper.accessor('closed_pnl', {
    header: 'Closed PnL',
    cell: (info) => <PnlDisplay value={info.getValue()} compact />,
    size: 110,
  }),
  columnHelper.accessor('fee_usd', {
    header: 'Fee',
    cell: (info) => (
      <span className="font-mono-nums text-xs text-text-muted">{formatUsd(info.getValue())}</span>
    ),
    size: 80,
  }),
];

interface TradeHistoryTableProps {
  data: TradeItem[];
}

export function TradeHistoryTable({ data }: TradeHistoryTableProps) {
  const isMobile = useIsMobile();

  if (isMobile) {
    return <TradeHistoryCardList data={data} />;
  }

  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: true }]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  return (
    <div className="rounded-lg border border-border">
      <div className="overflow-x-auto">
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
              <tr key={row.id} className="border-b border-border transition-colors hover:bg-card/50">
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

      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
          <span className="text-xs text-text-muted">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()} ({data.length} trades)
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="rounded p-1 text-text-muted transition-colors hover:bg-surface hover:text-text-primary disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="rounded p-1 text-text-muted transition-colors hover:bg-surface hover:text-text-primary disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
