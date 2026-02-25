import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Search, Clock, ArrowRight } from 'lucide-react';
import { PageLayout } from '../components/layout/PageLayout';

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const HISTORY_KEY = 'assess-history';
const MAX_HISTORY = 10;

function getHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch {
    return [];
  }
}

function addToHistory(address: string) {
  const history = getHistory().filter((a) => a !== address);
  history.unshift(address);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
}

export function AssessTrader() {
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const history = getHistory();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = address.trim().toLowerCase();
    if (!ADDRESS_RE.test(trimmed)) {
      setError('Invalid address. Expected 0x followed by 40 hex characters.');
      return;
    }
    setError('');
    addToHistory(trimmed);
    navigate(`/assess/${trimmed}`);
  };

  return (
    <PageLayout
      title="Assess Trader"
      description="Evaluate any Hyperliquid trader address across 10 independent scoring strategies. Get a quality verdict with confidence tier based on how many strategies the address passes."
    >
      <div className="mx-auto max-w-2xl pt-12">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={address}
              onChange={(e) => { setAddress(e.target.value); setError(''); }}
              placeholder="Enter trader address (0x...)"
              className="w-full rounded-lg border border-border bg-card py-3 pl-12 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent font-mono"
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-red">{error}</p>}
          <button
            type="submit"
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
            disabled={!address.trim()}
          >
            Assess Trader
          </button>
        </form>

        {history.length > 0 && (
          <div className="mt-8">
            <h3 className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-muted">
              <Clock className="h-3.5 w-3.5" />
              Recent Assessments
            </h3>
            <div className="space-y-1">
              {history.map((addr) => (
                <button
                  key={addr}
                  onClick={() => { addToHistory(addr); navigate(`/assess/${addr}`); }}
                  className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left font-mono text-sm text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
                >
                  <span className="truncate">{addr}</span>
                  <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </PageLayout>
  );
}
