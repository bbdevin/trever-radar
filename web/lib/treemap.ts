/** Squarified treemap(Bruls et al.)— 輸入 value 陣列與容器寬高,輸出各項矩形。 */

export interface TreeRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function squarify(values: number[], width: number, height: number): TreeRect[] {
  const total = values.reduce((a, b) => a + b, 0);
  const rects: TreeRect[] = new Array(values.length);
  if (total <= 0 || values.length === 0) return rects.fill({ x: 0, y: 0, w: 0, h: 0 });

  // 面積正規化
  const areas = values.map((v) => (v / total) * width * height);
  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let row: number[] = [];
  let rowStart = 0;

  const worst = (r: number[], side: number) => {
    const s = r.reduce((a, b) => a + b, 0);
    const max = Math.max(...r);
    const min = Math.min(...r);
    return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
  };

  const layoutRow = (r: number[], startIdx: number) => {
    const s = r.reduce((a, b) => a + b, 0);
    const horizontal = w >= h; // 沿短邊排
    const side = horizontal ? h : w;
    const thick = s / side;
    let offset = 0;
    for (let i = 0; i < r.length; i++) {
      const len = r[i] / thick;
      rects[startIdx + i] = horizontal
        ? { x, y: y + offset, w: thick, h: len }
        : { x: x + offset, y, w: len, h: thick };
      offset += len;
    }
    if (horizontal) {
      x += thick;
      w -= thick;
    } else {
      y += thick;
      h -= thick;
    }
  };

  for (let i = 0; i < areas.length; i++) {
    const side = Math.min(w, h);
    if (row.length === 0 || worst([...row, areas[i]], side) <= worst(row, side)) {
      row.push(areas[i]);
    } else {
      layoutRow(row, rowStart);
      rowStart = i;
      row = [areas[i]];
    }
  }
  if (row.length) layoutRow(row, rowStart);
  return rects;
}
