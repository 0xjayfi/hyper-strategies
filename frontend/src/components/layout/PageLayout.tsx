import { type ReactNode, useState } from 'react';
import { Info, ChevronDown, ChevronUp } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { Header } from './Header';

interface PageLayoutProps {
  title: string;
  description?: string;
  lastUpdated?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  children: ReactNode;
}

export function PageLayout({ title, description, lastUpdated, onRefresh, isRefreshing, children }: PageLayoutProps) {
  const [showDesc, setShowDesc] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          title={title}
          lastUpdated={lastUpdated}
          onRefresh={onRefresh}
          isRefreshing={isRefreshing}
          onMenuToggle={() => setMobileNavOpen(true)}
        />
        <main className="flex-1 overflow-y-auto overflow-x-hidden p-4 md:p-6">
          {description && (
            <div className="mb-4 rounded-lg border border-border bg-card">
              <button
                onClick={() => setShowDesc((v) => !v)}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-text-muted hover:text-text-primary transition-colors"
              >
                <Info className="h-3.5 w-3.5 shrink-0" />
                <span className="font-medium">About this page</span>
                {showDesc ? <ChevronUp className="ml-auto h-3.5 w-3.5" /> : <ChevronDown className="ml-auto h-3.5 w-3.5" />}
              </button>
              {showDesc && (
                <div className="border-t border-border px-4 py-3 text-xs leading-relaxed text-text-muted whitespace-pre-line">
                  {description}
                </div>
              )}
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
