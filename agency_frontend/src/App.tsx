import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ThemeProvider } from "@/hooks/use-theme";
import MakeCall from "./pages/MakeCall";
import CallHistory from "./pages/CallHistory";
import FollowUps from "./pages/FollowUps";
import Analytics from "./pages/Analytics";
import CustomData from "./pages/CustomData";
import Chat from "./pages/Chat";
import Account from "./pages/Account";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/make-call" replace />} />
            <Route path="/make-call" element={<MakeCall />} />
            <Route path="/call-history" element={<CallHistory />} />
            <Route path="/follow-ups" element={<FollowUps />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/custom-data" element={<CustomData />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/account" element={<Account />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </ThemeProvider>
  </QueryClientProvider>
);

export default App;