"use client";

import type { PressureMap } from "@/lib/api";
import { fmtUpTo4Decimals, niceAxisRange } from "@/lib/utils";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { LineChart } from "echarts/charts";
import {
    GridComponent,
    TitleComponent,
    ToolboxComponent,
    TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useMemo } from "react";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  ToolboxComponent,
  TitleComponent,
  CanvasRenderer,
]);

interface Props {
  map: PressureMap;
  frame: number;
}

export function PressureAnimationChart({ map, frame }: Props) {
  // Defensive: old in-memory simulation results may not have pressure_map yet.
  if (!map?.times_days?.length) return null;

  const n = map.times_days.length;
  const idx = Math.min(frame, n - 1);
  const t = map.times_days[idx];
  const po = map.oil_pressure_psi[idx];
  const pw = map.water_pressure_psi[idx];

  const dx = map.x_m.length > 1 ? map.x_m[1] - map.x_m[0] : map.x_m[0];
  const L = map.x_m[map.x_m.length - 1] + dx / 2;

  const oilData = useMemo(() => map.x_m.map((x, i) => [x, po[i]]), [po, map.x_m]);
  const waterData = useMemo(() => map.x_m.map((x, i) => [x, pw[i]]), [pw, map.x_m]);

  // fixed, evenly-spaced y-axis ranges so the scale doesn't jump during playback
  const oilAxis = useMemo(
    () =>
      niceAxisRange(
        Math.min(...map.oil_pressure_psi.flat()),
        Math.max(...map.oil_pressure_psi.flat())
      ),
    [map.oil_pressure_psi]
  );
  const waterAxis = useMemo(
    () =>
      niceAxisRange(
        Math.min(...map.water_pressure_psi.flat()),
        Math.max(...map.water_pressure_psi.flat())
      ),
    [map.water_pressure_psi]
  );

  return (
    <div>
      <ReactEChartsCore
        echarts={echarts}
        option={{
          title: {
            text: "Oil / water pressure",
            left: "center",
            textStyle: { fontSize: 14 },
          },
          tooltip: {
            trigger: "axis",
            formatter: (ps: { value: number[]; seriesName: string }[] | { value: number[]; seriesName: string }) => {
              const p = Array.isArray(ps) ? ps[0] : ps;
              const [x, v] = p.value;
              return `${p.seriesName}<br/>x = ${x.toFixed(3)} m<br/>p = ${fmtUpTo4Decimals(v)} psi`;
            },
          },
          grid: [
            { top: 48, left: 65, right: 30, height: 150 },
            { top: 248, left: 65, right: 30, height: 150 },
          ],
          toolbox: {
            feature: { saveAsImage: { title: "Save" } },
            right: 10,
            top: 0,
          },
          xAxis: [
            {
              gridIndex: 0,
              type: "value",
              min: 0,
              max: L,
              axisLabel: { show: false },
              axisTick: { show: false },
            },
            {
              gridIndex: 1,
              type: "value",
              min: 0,
              max: L,
              name: "Distance from inlet (m)",
              nameLocation: "center",
              nameGap: 28,
              axisLabel: { fontSize: 10 },
            },
          ],
          yAxis: [
            {
              gridIndex: 0,
              type: "value",
              name: "Oil pressure (psi)",
              min: oilAxis.min,
              max: oilAxis.max,
              interval: oilAxis.interval,
            },
            {
              gridIndex: 1,
              type: "value",
              name: "Water pressure (psi)",
              min: waterAxis.min,
              max: waterAxis.max,
              interval: waterAxis.interval,
            },
          ],
          series: [
            {
              name: "Oil",
              type: "line",
              xAxisIndex: 0,
              yAxisIndex: 0,
              data: oilData,
              showSymbol: false,
              lineStyle: { width: 2, color: "#ef4444" },
            },
            {
              name: "Water",
              type: "line",
              xAxisIndex: 1,
              yAxisIndex: 1,
              data: waterData,
              showSymbol: false,
              lineStyle: { width: 2, color: "#3b82f6" },
            },
          ],
        }}
        style={{ height: 420, width: "100%" }}
      />
    </div>
  );
}
