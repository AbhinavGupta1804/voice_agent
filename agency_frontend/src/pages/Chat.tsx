import { MessageSquare } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";

export default function Chat() {
  return (
    <DashboardLayout>
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <div className="bg-card rounded-2xl shadow-card p-12 text-center max-w-md">
          <div className="h-20 w-20 mx-auto rounded-full bg-accent flex items-center justify-center mb-6">
            <MessageSquare className="h-10 w-10 text-muted-foreground" />
          </div>
          <h1 className="text-2xl font-bold text-card-foreground mb-3">
            Chat Coming Soon
          </h1>
          <p className="text-muted-foreground">
            We're building something amazing. Stay tuned for our AI-powered chat feature.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
}