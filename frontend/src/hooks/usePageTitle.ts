import { useEffect } from 'react';

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | Hyper-Signals`;
    return () => { document.title = 'Hyper-Signals'; };
  }, [title]);
}
