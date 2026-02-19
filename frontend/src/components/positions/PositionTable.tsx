import { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import type { TokenPerpPosition } from '../../api/types';
import { formatUsd, truncateAddress, formatLeverage } from '../../lib/utils';
import { SideBadge } from '../shared/SideBadge';
import { PnlDisplay } from '../shared/PnlDisplay';
import { SmartMoneyBadge } from '../shared/SmartMoneyBadge';
import { PositionRowDetail } from './PositionRowDetail';

const columnHelper = createColumnHelper<TokenPerpPosition>();

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
          {row.address_label && (
            <span className="text-xs text-text-primary">{row.address_label}</span>
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
  columnHelper.accessor('side', {
    header: 'Side',
    cell: (info) => <SideBadge side={info.getValue()} />,
    size: 80,
  }),
  columnHelper.accessor('position_value_usd', {
    header: 'Size',
    cell: (info) => (
      <span className="font-mono-nums">{formatUsd(info.getValue(), true)}</span>
    ),
    size: 100,
  }),
  columnHelper.accessor('leverage', {
    header: 'Leverage',
    cell: (info) => (
      <span className="font-mono-nums">{formatLeverage(info.getValue())}</span>
    ),
    size: 80,
  }),
  columnHelper.accessor('entry_price', {
    header: 'Entry',
    cell: (info) => (
      <span className="font-mono-nums">{formatUsd(info.getValue())}</span>
    ),
    size: 100,
  }),
  columnHelper.accessor('mark_price', {
    header: 'Mark',
    cell: (info) => (
      <span className="font-mono-nums">{formatUsd(info.getValue())}</span>
    ),
    size: 100,
  }),
  columnHelper.accessor('liquidation_price', {
    header: 'Liq Price',
    cell: (info) => {
      const val = info.getValue();
      return (
        <span className="font-mono-nums text-text-muted">
          {val != null ? formatUsd(val) : '---'}
        </span>
      );
    },
    size: 100,
  }),
  columnHelper.accessor('upnl_usd', {
    header: 'uPnL',
    cell: (info) => <PnlDisplay value={info.getValue()} compact />,
    size: 100,
  }),
];

interface PositionTableProps {
  data: TokenPerpPosition[];
}

export function PositionTable({ data }: PositionTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const toggleRow = (index: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const _rows = useMemo(() => table.getRowModel().rows, [table.getRowModel().rows]);

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
          {_rows.map((row) => (
            <tbody key={row.id}>
              <tr
                className="cursor-pointer border-b border-border transition-colors hover:bg-card/50"
                onClick={() => toggleRow(row.index)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2.5">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
              {expandedRows.has(row.index) && (
                <tr>
                  <td colSpan={columns.length}>
                    <PositionRowDetail position={row.original} />
                  </td>
                </tr>
              )}
            </tbody>
          ))}
        </tbody>
      </table>
    </div>
  );
}
