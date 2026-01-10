import { User, Mail, Phone, Share2, Copy } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";

export default function Account() {
  const user = {
    name: "John Doe",
    email: "john@example.com",
    phone: "+1 (555) 123-4567",
    totalCalls: 156,
    referralCode: "JOHN2024",
  };

  const copyReferralCode = () => {
    navigator.clipboard.writeText(`https://callai.app/ref/${user.referralCode}`);
    toast({ title: "Copied!", description: "Referral link copied to clipboard" });
  };

  return (
    <DashboardLayout>
      <div className="max-w-2xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">Account Details</h1>
          <p className="text-muted-foreground mt-2">
            Manage your account settings and preferences
          </p>
        </header>

        {/* Profile Card */}
        <div className="bg-card rounded-2xl shadow-card p-8 mb-6">
          <div className="flex items-center gap-6 mb-8">
            <div className="h-20 w-20 rounded-full bg-accent flex items-center justify-center">
              <User className="h-10 w-10 text-muted-foreground" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-card-foreground">{user.name}</h2>
              <p className="text-muted-foreground">Premium Member</p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center gap-4 p-4 bg-accent/50 rounded-xl">
              <Mail className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-sm text-muted-foreground">Email</p>
                <p className="font-medium text-card-foreground">{user.email}</p>
              </div>
            </div>

            <div className="flex items-center gap-4 p-4 bg-accent/50 rounded-xl">
              <Phone className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-sm text-muted-foreground">Phone</p>
                <p className="font-medium text-card-foreground">{user.phone}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Stats Card */}
        <div className="bg-card rounded-2xl shadow-card p-8 mb-6">
          <h3 className="font-semibold text-card-foreground mb-4">Usage Statistics</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-accent/50 rounded-xl text-center">
              <p className="text-3xl font-bold text-card-foreground">{user.totalCalls}</p>
              <p className="text-sm text-muted-foreground">Total Calls</p>
            </div>
            <div className="p-4 bg-accent/50 rounded-xl text-center">
              <p className="text-3xl font-bold text-card-foreground">21%</p>
              <p className="text-sm text-muted-foreground">Conversion Rate</p>
            </div>
          </div>
        </div>

        {/* Referral Card */}
        <div className="bg-card rounded-2xl shadow-card p-8">
          <div className="flex items-center gap-3 mb-4">
            <Share2 className="h-5 w-5 text-muted-foreground" />
            <h3 className="font-semibold text-card-foreground">Refer a Friend</h3>
          </div>
          <p className="text-muted-foreground text-sm mb-4">
            Share CallAI with friends and earn credits when they sign up!
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1 p-3 bg-accent/50 rounded-lg font-mono text-sm text-card-foreground truncate">
              https://callai.app/ref/{user.referralCode}
            </div>
            <Button onClick={copyReferralCode} size="icon" variant="secondary">
              <Copy className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}