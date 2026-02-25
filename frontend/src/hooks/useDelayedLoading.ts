import { useState, useEffect } from 'react';

export function useDelayedLoading(delayMs: number = 300): boolean {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShow(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  return show;
}
