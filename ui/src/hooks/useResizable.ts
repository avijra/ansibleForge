import { useCallback, useRef, useState } from "react";

interface UseResizableOptions {
  direction: "horizontal" | "vertical";
  initialSize: number;
  minSize?: number;
  maxSize?: number;
}

export function useResizable({ direction, initialSize, minSize = 100, maxSize = Infinity }: UseResizableOptions) {
  const [size, setSize] = useState(initialSize);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startSize = useRef(0);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startPos.current = direction === "horizontal" ? e.clientX : e.clientY;
      startSize.current = size;

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const delta = direction === "horizontal"
          ? startPos.current - ev.clientX
          : startPos.current - ev.clientY;
        const newSize = Math.min(maxSize, Math.max(minSize, startSize.current + delta));
        setSize(newSize);
      };

      const onMouseUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [direction, size, minSize, maxSize]
  );

  return { size, setSize, onMouseDown };
}
