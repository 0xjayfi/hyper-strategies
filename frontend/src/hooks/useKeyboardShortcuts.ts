import { useEffect } from 'react';
import { useNavigate } from 'react-router';

export function useKeyboardShortcuts() {
  const navigate = useNavigate();

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Don't trigger if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case '1': navigate('/'); break;
        case '2': navigate('/positions'); break;
        case '3': navigate('/leaderboard'); break;
        case '4': navigate('/allocations'); break;
        case '5': navigate('/assess'); break;
        case 'r':
          if (!e.ctrlKey && !e.metaKey) {
            window.dispatchEvent(new CustomEvent('hyper-refresh'));
          }
          break;
      }
    }

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [navigate]);
}
