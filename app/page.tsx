"use client";

import { PressureAnimationChart } from "@/components/charts/pressure-animation-chart";
import { PropertyCharts } from "@/components/charts/property-charts";
import { RecoveryAnimationChart } from "@/components/charts/recovery-animation-chart";
import { SaturationAnimationChart } from "@/components/charts/saturation-animation-chart";
import { SimulationForm } from "@/components/simulation-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  computeProperties,
  runSimulation,
  type PropertiesResponse,
  type SimulationRequest,
  type SimulationResponse,
} from "@/lib/api";
import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

const FPS = 12;

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [simData, setSimData] = useState<SimulationResponse | null>(null);
  const [propData, setPropData] = useState<PropertiesResponse | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);

  const nFrames = simData ? simData.saturation_map.times_days.length : 0;
  const currentTime =
    simData?.saturation_map.times_days[Math.min(frame, Math.max(nFrames - 1, 0))] ?? 0;

  // restart animation when a new simulation arrives
  useEffect(() => {
    if (simData) {
      setFrame(0);
      setPlaying(true);
    }
  }, [simData]);

  // shared playback loop
  useEffect(() => {
    if (!playing || !simData || nFrames === 0) return;
    const id = setInterval(() => setFrame((f) => (f + 1) % nFrames), 1000 / FPS);
    return () => clearInterval(id);
  }, [playing, simData, nFrames]);

  const handleParamsChange = useCallback(async (params: SimulationRequest) => {
    try {
      const props = await computeProperties(params);
      setPropData(props);
    } catch {
      // silently ignore property fetch errors
    }
  }, []);

  const handleSubmit = useCallback(async (params: SimulationRequest) => {
    setLoading(true);
    setError(null);
    try {
      const [sim, props] = await Promise.all([
        runSimulation(params),
        computeProperties(params),
      ]);
      setSimData(sim);
      setPropData(props);
      setActiveTab(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold tracking-tight">
            Countercurrent Imbibition Simulator
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Pooladi-Darvish & Firoozabadi, SPE Journal (2000) -- 1D nonlinear diffusion model
          </p>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        <Tabs value={activeTab} onValueChange={(v) => {
          const idx = typeof v === "number" ? v : Number(v);
          if (!isNaN(idx)) setActiveTab(idx);
        }}>
          <TabsList className="mb-6">
            <TabsTrigger value={0}>Setup</TabsTrigger>
            <TabsTrigger value={1}>Results</TabsTrigger>
          </TabsList>

          {/* ── Setup tab ─────────────────────────────────────────── */}
          <TabsContent value={0} className="space-y-6">
            <SimulationForm
              onSubmit={handleSubmit}
              onParamsChange={handleParamsChange}
              loading={loading}
            />

            {error && (
              <Card className="border-destructive">
                <CardContent className="py-4 text-destructive text-sm">{error}</CardContent>
              </Card>
            )}

            {/* Property charts (live on Setup tab) */}
            {propData && (
              <>
                <Separator />
                <h2 className="text-lg font-semibold">Rock & Fluid Properties</h2>
                <PropertyCharts data={propData} />
              </>
            )}
          </TabsContent>

          {/* ── Results tab ───────────────────────────────────────── */}
          <TabsContent value={1} className="space-y-6">
            {!simData ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground">
                  Adjust parameters on the Setup tab and click{" "}
                  <span className="font-medium text-foreground">Run Simulation</span>{" "}
                  to see results here.
                </CardContent>
              </Card>
            ) : (
              <>
                {/* Summary stats */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Summary</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
                      <StatCard
                        label="Front at 1 day"
                        value={
                          simData.summary.front_position_1d_cm != null
                            ? `${simData.summary.front_position_1d_cm.toFixed(2)} cm`
                            : "beyond L"
                        }
                      />
                      <StatCard
                        label="Oil pressure (behind front)"
                        value={`${simData.summary.oil_pressure_behind_front_kPa.toFixed(2)} kPa`}
                      />
                      <StatCard
                        label="Water pressure at Si"
                        value={`${simData.summary.water_pressure_at_Si_kPa.toFixed(2)} kPa`}
                      />
                      <StatCard
                        label="Half-recovery time"
                        value={
                          simData.summary.half_recovery_days != null
                            ? `${simData.summary.half_recovery_days.toFixed(1)} days`
                            : "> tmax"
                        }
                      />
                      <StatCard
                        label="Mass balance error"
                        value={simData.summary.mass_balance_error.toExponential(2)}
                      />
                    </div>
                  </CardContent>
                </Card>

                <Separator />

                {/* Shared animation controls */}
                <Card>
                  <CardContent className="py-3">
                    <div className="flex items-center gap-3">
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setPlaying((p) => !p)}
                        aria-label={playing ? "Pause" : "Play"}
                      >
                        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </Button>
                      <Slider
                        min={0}
                        max={Math.max(nFrames - 1, 1)}
                        step={1}
                        value={[Math.min(frame, Math.max(nFrames - 1, 0))]}
                        onValueChange={(next) => {
                          const v = Array.isArray(next) ? next[0] : next;
                          if (v != null) setFrame(v);
                        }}
                        className="flex-1"
                      />
                      <span className="w-24 text-right text-sm font-mono tabular-nums text-muted-foreground">
                        t = {currentTime.toFixed(2)} d
                      </span>
                    </div>
                  </CardContent>
                </Card>

                {/* Saturation timelapse: profile + colored core (full width) */}
                <Card>
                  <CardContent className="pt-6">
                    <SaturationAnimationChart map={simData.saturation_map} frame={frame} />
                  </CardContent>
                </Card>

                {/* Oil + water pressure timelapse (full width) */}
                <Card>
                  <CardContent className="pt-6">
                    <PressureAnimationChart map={simData.pressure_map} frame={frame} />
                  </CardContent>
                </Card>

                {/* Recovery factor timelapse */}
                <Card>
                  <CardContent className="pt-6">
                    <RecoveryAnimationChart
                      numerical={simData.recovery_curve}
                      analytical={simData.analytical_recovery}
                      frameTimes={simData.saturation_map.times_days}
                      frame={frame}
                    />
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="font-semibold font-mono mt-0.5">{value}</p>
    </div>
  );
}
