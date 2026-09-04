import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'button:not(:disabled):not(.visually-hidden), input:not(:disabled):not(.visually-hidden), select:not(:disabled):not(.visually-hidden), textarea:not(:disabled):not(.visually-hidden), a[href], [tabindex]:not([tabindex="-1"]):not(.visually-hidden)';

export function useModal(open: boolean, onClose: () => void, initialFocus?: RefObject<HTMLElement | null>) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const background = document.querySelector<HTMLElement>(".app-shell");
    if (background) background.inert = true;
    const focus = window.setTimeout(() => (initialFocus?.current ?? dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); return; }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const items = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0];
      const last = items.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focus);
      document.removeEventListener("keydown", onKeyDown);
      if (background) background.inert = false;
    };
  }, [initialFocus, open]);

  return dialogRef;
}
