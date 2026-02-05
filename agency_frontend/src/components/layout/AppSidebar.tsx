import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Phone,
  History,
  PhoneCall,
  BarChart3,
  Database,
  MessageSquare,
  User,
  LogOut,
  Settings,
  Moon,
  Sun,
  ChevronUp,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/use-theme";

const navItems = [
  { title: "Make Call", url: "/make-call", icon: Phone },
  { title: "Call History", url: "/call-history", icon: History },
  { title: "Follow-ups", url: "/follow-ups", icon: PhoneCall },
  { title: "Analytics", url: "/analytics", icon: BarChart3 },
  { title: "Custom Data", url: "/custom-data", icon: Database },
  { title: "Chat", url: "/chat", icon: MessageSquare },
];

export function AppSidebar() {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-64 bg-sidebar border-r border-sidebar-border flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-sidebar-border">
        <h1 className="text-xl font-bold text-sidebar-primary tracking-tight">
          AllOutReachOut.ai
        </h1>
        <p className="text-xs text-sidebar-foreground mt-1">AI-Powered Outreach</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => {
          const isActive = location.pathname === item.url;
          return (
            <NavLink
              key={item.url}
              to={item.url}
              className={cn(
                "flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-soft"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
              )}
            >
              <item.icon className="h-5 w-5" />
              <span>{item.title}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* User Profile */}
      <div className="p-4 border-t border-sidebar-border">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="w-full flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-sidebar-accent/50 transition-colors">
              <div className="h-10 w-10 rounded-full bg-sidebar-accent flex items-center justify-center">
                <User className="h-5 w-5 text-sidebar-foreground" />
              </div>
              <div className="flex-1 text-left">
                <p className="text-sm font-medium text-sidebar-accent-foreground">
                  Aditya Sakpal
                </p>
                <p className="text-xs text-sidebar-foreground">adi243@gmail.com</p>
              </div>
              <ChevronUp className="h-4 w-4 text-sidebar-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            side="top"
            className="w-56 bg-popover border border-border shadow-elevated"
          >
            <DropdownMenuItem asChild>
              <NavLink to="/account" className="flex items-center gap-2 cursor-pointer">
                <Settings className="h-4 w-4" />
                <span>Account Details</span>
              </NavLink>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={toggleTheme} className="flex items-center gap-2 cursor-pointer">
              {theme === "light" ? (
                <>
                  <Moon className="h-4 w-4" />
                  <span>Dark Mode</span>
                </>
              ) : (
                <>
                  <Sun className="h-4 w-4" />
                  <span>Light Mode</span>
                </>
              )}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="flex items-center gap-2 cursor-pointer text-destructive focus:text-destructive">
              <LogOut className="h-4 w-4" />
              <span>Logout</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  );
}