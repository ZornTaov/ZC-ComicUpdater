// touch and mouse on the page, as one stream of pointers: a tap turns or opens the menu, a sideways swipe
// turns, two fingers zoom, one finger pans a zoomed page or scrolls one taller than the screen. done by
// hand rather than left to the browser, which would zoom the whole page and turn nothing.
export interface GestureHandlers {
  tap(x: number, y: number): void;
  // a second tap in the middle soon after the first: zoom in there, or back out
  doubleTap(x: number, y: number): void;
  swipe(direction: "left" | "right"): void;
  // a one-finger drag on an unzoomed page: the stage scrolls by it
  drag(dx: number, dy: number): void;
  // two fingers, or a pan of a zoomed page
  zoom(scale: number, originX: number, originY: number, panX: number, panY: number): void;
  scale(): number;
  // whether a tap here is in the middle, where a double tap is waited for
  middle(x: number): boolean;
}

const TAP_SLOP = 10;
const SWIPE = 50;
const DOUBLE = 280;

export function attachGestures(target: HTMLElement, on: GestureHandlers): () => void {
  const pointers = new Map<number, { x: number; y: number; startX: number; startY: number; at: number }>();
  let pinch: { distance: number; scale: number } | null = null;
  let moved = false;
  let lastTap = 0;
  let pendingTap: number | undefined;

  const down = (event: PointerEvent) => {
    // a video's controls, or flash being played, take their own taps; capturing them here would turn the
    // page under a finger pressing play
    if ((event.target as Element).closest?.(".embed")) return;
    target.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
                                    at: performance.now() });
    moved = pointers.size > 1 ? true : false;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: on.scale() };
    }
  };

  const move = (event: PointerEvent) => {
    const held = pointers.get(event.pointerId);
    if (!held) return;
    const dx = event.clientX - held.x;
    const dy = event.clientY - held.y;
    held.x = event.clientX;
    held.y = event.clientY;
    if (Math.hypot(held.x - held.startX, held.y - held.startY) > TAP_SLOP) moved = true;
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      on.zoom(Math.max(1, Math.min(6, pinch.scale * distance / pinch.distance)), (a.x + b.x) / 2, (a.y + b.y) / 2,
              dx / 2, dy / 2);
    } else if (pointers.size === 1 && moved) {
      if (on.scale() > 1.01) on.zoom(on.scale(), 0, 0, dx, dy);
      else if (event.pointerType !== "mouse") on.drag(dx, dy);
    }
  };

  const up = (event: PointerEvent) => {
    const held = pointers.get(event.pointerId);
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!held || pointers.size > 0) return;
    const totalX = held.x - held.startX;
    const totalY = held.y - held.startY;
    if (!moved) {
      const now = performance.now();
      if (on.middle(held.x)) {
        // only the middle waits to see whether a second tap follows; a tap on either side turns at once
        if (now - lastTap < DOUBLE) {
          window.clearTimeout(pendingTap);
          lastTap = 0;
          on.doubleTap(held.x, held.y);
          return;
        }
        lastTap = now;
        const x = held.x, y = held.y;
        pendingTap = window.setTimeout(() => on.tap(x, y), DOUBLE);
        return;
      }
      lastTap = 0;
      on.tap(held.x, held.y);
      return;
    }
    if (on.scale() <= 1.01 && Math.abs(totalX) > SWIPE && Math.abs(totalX) > Math.abs(totalY) * 1.5
        && performance.now() - held.at < 600) {
      on.swipe(totalX < 0 ? "left" : "right");
    }
  };

  const cancel = (event: PointerEvent) => {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = null;
  };

  target.addEventListener("pointerdown", down);
  target.addEventListener("pointermove", move);
  target.addEventListener("pointerup", up);
  target.addEventListener("pointercancel", cancel);
  return () => {
    window.clearTimeout(pendingTap);
    target.removeEventListener("pointerdown", down);
    target.removeEventListener("pointermove", move);
    target.removeEventListener("pointerup", up);
    target.removeEventListener("pointercancel", cancel);
  };
}
