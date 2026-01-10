import { useState } from "react";
import { Phone, Users, Upload, ArrowRight, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/hooks/use-toast";
import {
  useInitiateCall,
  useInitiateBulkCalls,
  useInitiateBulkCallsFromCSV,
} from "@/hooks/use-calls";
import type { CallRecipient } from "@/lib/types";

type CallType = "single" | "bulk" | "csv";

interface BulkCallResult {
  success: boolean;
  total: number;
  successful: number;
  failed: number;
}

export default function MakeCall() {
  const [activeTab, setActiveTab] = useState<CallType>("single");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [clientName, setClientName] = useState("");
  const [bulkNumbers, setBulkNumbers] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkCallResult | null>(null);

  const initiateCallMutation = useInitiateCall();
  const initiateBulkCallsMutation = useInitiateBulkCalls();
  const initiateCSVCallsMutation = useInitiateBulkCallsFromCSV();

  const handleSingleCall = async () => {
    if (!phoneNumber) {
      toast({ title: "Error", description: "Please enter a phone number", variant: "destructive" });
      return;
    }
    if (!clientName) {
      toast({ title: "Error", description: "Please enter a client name", variant: "destructive" });
      return;
    }

    try {
      const response = await initiateCallMutation.mutateAsync({
        number: phoneNumber,
        client_name: clientName,
      });
      
      toast({
        title: "Call Initiated",
        description: `Calling ${response.clientName} at ${response.phoneNumber}...`,
      });
      
      // Clear form on success
      setPhoneNumber("");
      setClientName("");
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to initiate call";
      toast({
        title: "Error",
        description: errorMessage,
        variant: "destructive",
      });
    }
  };

  const handleBulkCall = async () => {
    if (!bulkNumbers) {
      toast({ title: "Error", description: "Please enter phone numbers", variant: "destructive" });
      return;
    }

    // Parse bulk numbers - expects format: "name,phone" per line
    const lines = bulkNumbers.split("\n").filter((line) => line.trim());
    const recipients: CallRecipient[] = [];

    for (const line of lines) {
      const parts = line.split(",").map((p) => p.trim());
      if (parts.length >= 2) {
        recipients.push({
          client_name: parts[0],
          number: parts[1],
        });
      } else if (parts.length === 1 && parts[0]) {
        // If only phone number provided, use "Unknown" as name
        recipients.push({
          client_name: "Unknown",
          number: parts[0],
        });
      }
    }

    if (recipients.length === 0) {
      toast({
        title: "Error",
        description: "No valid phone numbers found. Use format: Name, Phone per line",
        variant: "destructive",
      });
      return;
    }

    try {
      setBulkResult(null);
      const response = await initiateBulkCallsMutation.mutateAsync({ recipients });
      
      setBulkResult({
        success: response.successful > 0,
        total: response.total_requested,
        successful: response.successful,
        failed: response.failed,
      });

      if (response.successful > 0) {
        toast({
          title: "Bulk Calls Initiated",
          description: `${response.successful}/${response.total_requested} calls started successfully`,
        });
      }
      
      if (response.failed > 0) {
        toast({
          title: "Some Calls Failed",
          description: `${response.failed} calls could not be initiated`,
          variant: "destructive",
        });
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to initiate bulk calls";
      toast({
        title: "Error",
        description: errorMessage,
        variant: "destructive",
      });
    }
  };

  const handleCsvUpload = async () => {
    if (!csvFile) {
      toast({ title: "Error", description: "Please upload a CSV file", variant: "destructive" });
      return;
    }

    try {
      setBulkResult(null);
      const response = await initiateCSVCallsMutation.mutateAsync(csvFile);
      
      setBulkResult({
        success: response.successful > 0,
        total: response.total_requested,
        successful: response.successful,
        failed: response.failed,
      });

      if (response.successful > 0) {
        toast({
          title: "CSV Calls Initiated",
          description: `${response.successful}/${response.total_requested} calls started successfully`,
        });
      }
      
      if (response.failed > 0) {
        toast({
          title: "Some Calls Failed",
          description: `${response.failed} calls could not be initiated`,
          variant: "destructive",
        });
      }
      
      // Clear file on success
      setCsvFile(null);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to process CSV";
      toast({
        title: "Error",
        description: errorMessage,
        variant: "destructive",
      });
    }
  };

  const isLoading =
    initiateCallMutation.isPending ||
    initiateBulkCallsMutation.isPending ||
    initiateCSVCallsMutation.isPending;

  const tabs = [
    { id: "single" as const, label: "Single Call", icon: Phone },
    { id: "bulk" as const, label: "Bulk Call", icon: Users },
    { id: "csv" as const, label: "CSV Upload", icon: Upload },
  ];

  return (
    <DashboardLayout>
      <div className="max-w-4xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">Make a Call</h1>
          <p className="text-muted-foreground mt-2">
            Initiate AI-powered calls to your contacts
          </p>
        </header>

        {/* Tabs */}
        <div className="flex gap-2 mb-8">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                setBulkResult(null);
              }}
              className={`flex items-center gap-2 px-6 py-3 rounded-lg font-medium transition-all duration-200 ${
                activeTab === tab.id
                  ? "bg-card text-card-foreground shadow-card"
                  : "bg-transparent text-muted-foreground hover:bg-card/50"
              }`}
              disabled={isLoading}
            >
              <tab.icon className="h-5 w-5" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content Cards */}
        <div className="bg-card rounded-2xl shadow-card p-8">
          {activeTab === "single" && (
            <div className="space-y-6">
              <div className="flex items-center gap-4 p-4 bg-accent/50 rounded-xl">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                  <Phone className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-card-foreground">Single Call</h3>
                  <p className="text-sm text-muted-foreground">
                    Make a personalized AI call to one contact
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="clientName">Client Name</Label>
                  <Input
                    id="clientName"
                    placeholder="John Smith"
                    value={clientName}
                    onChange={(e) => setClientName(e.target.value)}
                    className="mt-2"
                    disabled={isLoading}
                  />
                </div>
                <div>
                  <Label htmlFor="phone">Phone Number</Label>
                  <Input
                    id="phone"
                    placeholder="+1 (555) 123-4567"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value)}
                    className="mt-2"
                    disabled={isLoading}
                  />
                </div>
                <Button
                  onClick={handleSingleCall}
                  className="w-full"
                  disabled={isLoading}
                >
                  {initiateCallMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Initiating Call...
                    </>
                  ) : (
                    <>
                      Start Call
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}

          {activeTab === "bulk" && (
            <div className="space-y-6">
              <div className="flex items-center gap-4 p-4 bg-accent/50 rounded-xl">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                  <Users className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-card-foreground">Bulk Call</h3>
                  <p className="text-sm text-muted-foreground">
                    Call multiple contacts at once
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="bulk-numbers">
                    Contacts (Name, Phone Number per line)
                  </Label>
                  <Textarea
                    id="bulk-numbers"
                    placeholder={`John Smith, +1 (555) 123-4567\nJane Doe, +1 (555) 234-5678\nBob Wilson, +1 (555) 345-6789`}
                    value={bulkNumbers}
                    onChange={(e) => setBulkNumbers(e.target.value)}
                    className="mt-2 min-h-[150px] font-mono text-sm"
                    disabled={isLoading}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Format: Name, Phone (one per line). Calls are made sequentially.
                  </p>
                </div>

                {bulkResult && (
                  <div
                    className={`p-4 rounded-lg flex items-center gap-3 ${
                      bulkResult.failed === 0
                        ? "bg-success/10 text-success"
                        : bulkResult.successful === 0
                        ? "bg-destructive/10 text-destructive"
                        : "bg-warning/10 text-warning"
                    }`}
                  >
                    {bulkResult.failed === 0 ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <XCircle className="h-5 w-5" />
                    )}
                    <span>
                      {bulkResult.successful} of {bulkResult.total} calls initiated
                      {bulkResult.failed > 0 && ` (${bulkResult.failed} failed)`}
                    </span>
                  </div>
                )}

                <Button
                  onClick={handleBulkCall}
                  className="w-full"
                  disabled={isLoading}
                >
                  {initiateBulkCallsMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Initiating Calls...
                    </>
                  ) : (
                    <>
                      Start Bulk Calls
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}

          {activeTab === "csv" && (
            <div className="space-y-6">
              <div className="flex items-center gap-4 p-4 bg-accent/50 rounded-xl">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                  <Upload className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-card-foreground">CSV Upload</h3>
                  <p className="text-sm text-muted-foreground">
                    Upload a CSV file with contact numbers
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div className="bg-accent/30 border border-border rounded-lg p-4">
                  <p className="text-sm font-semibold text-card-foreground mb-2">
                    CSV Requirements:
                  </p>
                  <ul className="text-xs text-muted-foreground space-y-1 list-disc list-inside mb-3">
                    <li>Must have exact column names: <strong className="text-foreground">client_name</strong> and <strong className="text-foreground">client_phone</strong></li>
                    <li>Calls are made sequentially (one at a time)</li>
                  </ul>
                  <p className="text-xs font-medium text-card-foreground mb-1">Example CSV format:</p>
                  <div className="mt-1 p-2 bg-card rounded font-mono text-xs border border-border">
                    <div className="text-foreground">client_name,client_phone</div>
                    <div className="text-muted-foreground">John Smith,+1234567890</div>
                    <div className="text-muted-foreground">Jane Doe,+1987654321</div>
                  </div>
                </div>
                <div
                  className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
                    csvFile
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  <input
                    type="file"
                    accept=".csv,.txt"
                    onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                    className="hidden"
                    id="csv-upload"
                    disabled={isLoading}
                  />
                  <label htmlFor="csv-upload" className="cursor-pointer">
                    <Upload className="h-10 w-10 mx-auto text-muted-foreground mb-4" />
                    <p className="text-sm font-medium text-card-foreground">
                      {csvFile ? csvFile.name : "Click to upload CSV"}
                    </p>
                  </label>
                </div>

                {bulkResult && (
                  <div
                    className={`p-4 rounded-lg flex items-center gap-3 ${
                      bulkResult.failed === 0
                        ? "bg-success/10 text-success"
                        : bulkResult.successful === 0
                        ? "bg-destructive/10 text-destructive"
                        : "bg-warning/10 text-warning"
                    }`}
                  >
                    {bulkResult.failed === 0 ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <XCircle className="h-5 w-5" />
                    )}
                    <span>
                      {bulkResult.successful} of {bulkResult.total} calls initiated
                      {bulkResult.failed > 0 && ` (${bulkResult.failed} failed)`}
                    </span>
                  </div>
                )}

                <Button
                  onClick={handleCsvUpload}
                  className="w-full"
                  disabled={!csvFile || isLoading}
                >
                  {initiateCSVCallsMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Processing CSV...
                    </>
                  ) : (
                    <>
                      Process CSV
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
