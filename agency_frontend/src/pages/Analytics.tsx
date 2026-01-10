import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { useAnalytics } from "@/hooks/use-analytics";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Funnel,
  FunnelChart,
  LabelList,
} from "recharts";

// Mock data for charts
const callsOverTimeData = [
  { date: "Mon", calls: 45 },
  { date: "Tue", calls: 52 },
  { date: "Wed", calls: 48 },
  { date: "Thu", calls: 61 },
  { date: "Fri", calls: 55 },
  { date: "Sat", calls: 32 },
  { date: "Sun", calls: 28 },
];

const conversionRateData = [
  { date: "Week 1", rate: 12 },
  { date: "Week 2", rate: 15 },
  { date: "Week 3", rate: 18 },
  { date: "Week 4", rate: 22 },
  { date: "Week 5", rate: 20 },
  { date: "Week 6", rate: 25 },
];

const callDurationData = [
  { range: "0-2min", count: 45 },
  { range: "2-5min", count: 82 },
  { range: "5-10min", count: 65 },
  { range: "10-15min", count: 38 },
  { range: "15+min", count: 22 },
];

const inquiryTypesData = [
  { name: "Website Development", value: 35, color: "hsl(220, 70%, 50%)" },
  { name: "Website Revamp", value: 28, color: "hsl(160, 60%, 45%)" },
  { name: "Website Redesign", value: 22, color: "hsl(30, 80%, 55%)" },
  { name: "Follow-up Scheduled", value: 15, color: "hsl(280, 65%, 60%)" },
];

const followUpStatusData = [
  { status: "Jan", scheduled: 20, completed: 18, missed: 2 },
  { status: "Feb", scheduled: 25, completed: 22, missed: 3 },
  { status: "Mar", scheduled: 30, completed: 27, missed: 3 },
  { status: "Apr", scheduled: 28, completed: 25, missed: 3 },
  { status: "May", scheduled: 35, completed: 32, missed: 3 },
];

const funnelData = [
  { name: "Calls", value: 321, fill: "hsl(220, 70%, 50%)" },
  { name: "Engaged", value: 245, fill: "hsl(220, 60%, 55%)" },
  { name: "Qualified", value: 156, fill: "hsl(220, 50%, 60%)" },
  { name: "Converted", value: 68, fill: "hsl(160, 60%, 45%)" },
];

const sentimentData = [
  { call: "Call 1", score: 85 },
  { call: "Call 2", score: 72 },
  { call: "Call 3", score: 91 },
  { call: "Call 4", score: 65 },
  { call: "Call 5", score: 88 },
  { call: "Call 6", score: 78 },
  { call: "Call 7", score: 82 },
];

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-card rounded-2xl shadow-card p-6">
      <h3 className="font-semibold text-card-foreground mb-4">{title}</h3>
      {children}
    </div>
  );
}

export default function Analytics() {
  const { data: analyticsData, isLoading, error } = useAnalytics('week');

  // Format duration from seconds to minutes
  const formatDuration = (seconds: number): string => {
    const minutes = seconds / 60;
    return `${minutes.toFixed(1)}m`;
  };

  // Format change percentage
  const formatChange = (change: number): string => {
    const sign = change >= 0 ? '+' : '';
    return `${sign}${change.toFixed(1)}%`;
  };

  // Get stats from real data or use defaults
  const stats = analyticsData?.overview
    ? [
        {
          label: "Total Calls",
          value: analyticsData.overview.total_calls.toString(),
          change: formatChange(analyticsData.overview.total_calls_change),
        },
        {
          label: "Avg Duration",
          value: formatDuration(analyticsData.overview.avg_duration_sec),
          change: formatChange(analyticsData.overview.avg_duration_change),
        },
        {
          label: "Conversion Rate",
          value: `${analyticsData.overview.conversion_rate.toFixed(1)}%`,
          change: formatChange(analyticsData.overview.conversion_rate_change),
        },
        {
          label: "Sentiment Score",
          value: analyticsData.overview.sentiment_score.toFixed(0),
          change: formatChange(analyticsData.overview.sentiment_change),
        },
      ]
    : [
        { label: "Total Calls", value: "0", change: "0%" },
        { label: "Avg Duration", value: "0m", change: "0%" },
        { label: "Conversion Rate", value: "0%", change: "0%" },
        { label: "Sentiment Score", value: "0", change: "0%" },
      ];

  return (
    <DashboardLayout>
      <div className="max-w-7xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">Analytics</h1>
          <p className="text-muted-foreground mt-2">
            Insights and metrics from your AI calls
          </p>
        </header>

        {/* Stats Overview */}
        {isLoading ? (
          <div className="grid grid-cols-4 gap-4 mb-8">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-card rounded-xl p-4 shadow-soft animate-pulse">
                <div className="h-4 bg-muted rounded w-20 mb-2"></div>
                <div className="h-8 bg-muted rounded w-16"></div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="bg-destructive/10 text-destructive rounded-xl p-4 mb-8">
            Failed to load analytics data. Please try again later.
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-4 mb-8">
            {stats.map((stat) => (
              <div key={stat.label} className="bg-card rounded-xl p-4 shadow-soft">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">{stat.label}</p>
                  <span className={`text-xs font-medium ${
                    parseFloat(stat.change) >= 0 ? 'text-success' : 'text-destructive'
                  }`}>
                    {stat.change}
                  </span>
                </div>
                <p className="text-2xl font-bold text-card-foreground mt-1">{stat.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Charts Grid */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Graph 1: Calls Over Time */}
          <ChartCard title="Calls Over Time">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={callsOverTimeData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="calls"
                  stroke="hsl(var(--chart-1))"
                  strokeWidth={2}
                  dot={{ fill: "hsl(var(--chart-1))" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Graph 2: Conversion Rate Trend */}
          <ChartCard title="Conversion Rate Trend">
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={conversionRateData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} unit="%" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="rate"
                  stroke="hsl(var(--chart-2))"
                  fill="hsl(var(--chart-2) / 0.2)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Graph 3: Call Duration Distribution */}
          <ChartCard title="Call Duration Distribution">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={callDurationData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="range" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
                <Bar dataKey="count" fill="hsl(var(--chart-3))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Graph 4: Inquiry Types Breakdown */}
          <ChartCard title="Inquiry Types">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={inquiryTypesData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {inquiryTypesData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 mt-2 justify-center">
              {inquiryTypesData.map((item) => (
                <div key={item.name} className="flex items-center gap-1 text-xs">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-muted-foreground">{item.name}</span>
                </div>
              ))}
            </div>
          </ChartCard>

          {/* Graph 5: Follow-Up Status */}
          <ChartCard title="Follow-Up Status">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={followUpStatusData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="status" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
                <Bar dataKey="completed" stackId="a" fill="hsl(var(--chart-2))" radius={[0, 0, 0, 0]} />
                <Bar dataKey="scheduled" stackId="a" fill="hsl(var(--chart-1))" radius={[0, 0, 0, 0]} />
                <Bar dataKey="missed" stackId="a" fill="hsl(var(--chart-5))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Graph 6: Conversion Funnel */}
          <ChartCard title="Conversion Funnel">
            <ResponsiveContainer width="100%" height={200}>
              <FunnelChart>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                  }}
                />
                <Funnel dataKey="value" data={funnelData} isAnimationActive>
                  <LabelList
                    position="center"
                    fill="hsl(var(--primary-foreground))"
                    stroke="none"
                    dataKey="name"
                    fontSize={12}
                  />
                </Funnel>
              </FunnelChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Graph 7: AI Sentiment Score */}
          <div className="lg:col-span-3">
            <ChartCard title="AI Sentiment Score per Call">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={sentimentData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis type="number" domain={[0, 100]} stroke="hsl(var(--muted-foreground))" fontSize={12} />
                  <YAxis dataKey="call" type="category" stroke="hsl(var(--muted-foreground))" fontSize={12} width={60} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "8px",
                    }}
                  />
                  <Bar dataKey="score" fill="hsl(var(--chart-4))" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}