"use client";

import { PressureChart } from "@/components/charts/pressure-charts";
import { PropertyCharts } from "@/components/charts/property-charts";
import { RecoveryChart } from "@/components/charts/recovery-chart";
import { SaturationChart } from "@/components/charts/saturation-chart";
import { SimulationForm } from "@/components/simulation-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    computeProperties,
    runSimulation,
    type PropertiesResponse,
    type SimulationRequest,
    type SimulationResponse,
} from "@/lib/api";
import { useCallback, useState } from "react";

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [simData, setSimData] = useState<SimulationResponse | null>(null);
  const [propData, setPropData] = useState<PropertiesResponse | null>(null);
  const [activeTab, setActiveTab] = useState(0);

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
                        value={`${simData.summary.oil_pressure_behind_front_psi.toFixed(2)} psi`}
                      />
                      <StatCard
                        label="Water pressure at Si"
                        value={`${simData.summary.water_pressure_at_Si_psi.toFixed(2)} psi`}
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

                {/* Saturation profiles (full width) */}
                <Card>
                  <CardContent className="pt-6">
                    <SaturationChart
                      numerical={simData.saturation_profiles}
                      analytical={simData.analytical_profiles}
                    />
                  </CardContent>
                </Card>

                {/* Pressure profiles (side by side) */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <Card>
                    <CardContent className="pt-6">
                      <PressureChart
                        profiles={simData.oil_pressure_profiles}
                        title="Oil Pressure Profiles"
                        yAxisName="Oil pressure (psi)"
                      />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="pt-6">
                      <PressureChart
                        profiles={simData.water_pressure_profiles}
                        title="Water Pressure Profiles"
                        yAxisName="Water pressure (psi)"
                      />
                    </CardContent>
                  </Card>
                </div>

                {/* Recovery curve */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <Card>
                    <CardContent className="pt-6">
                      <RecoveryChart
                        numerical={simData.recovery_curve}
                        analytical={simData.analytical_recovery}
                      />
                    </CardContent>
                  </Card>
                </div>
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
