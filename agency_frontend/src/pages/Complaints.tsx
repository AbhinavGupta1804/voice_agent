
import { useEffect, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Ticket } from "@/lib/types";
import { ticketService } from "@/lib/ticketService";
import { format } from "date-fns";
import { Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";

export default function Complaints() {
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchTickets = async () => {
        setLoading(true);
        const data = await ticketService.getAllTickets();
        setTickets(data);
        setLoading(false);
    };

    useEffect(() => {
        fetchTickets();
    }, []);

    const handleCloseTicket = async (id: number) => {
        const success = await ticketService.closeTicket(id);
        if (success) {
            // Optimistic update
            setTickets((prev) =>
                prev.map((t) => (t.ticket_id === id ? { ...t, status: "Closed" } : t))
            );
        }
    };

    const getPriorityColor = (priority: string) => {
        switch (priority) {
            case "High":
                return "destructive"; // Red
            case "Medium":
                return "default"; // Black/Primary
            case "Low":
                return "secondary"; // Gray
            default:
                return "outline";
        }
    };

    return (
        <DashboardLayout>
            <div className="space-y-6">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">Support Tickets</h2>
                    <p className="text-muted-foreground">Manage customer complaints and issues.</p>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle>Active Tickets</CardTitle>
                    </CardHeader>
                    <CardContent>
                        {loading ? (
                            <div className="flex justify-center p-8">
                                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                            </div>
                        ) : tickets.length === 0 ? (
                            <div className="text-center p-8 text-muted-foreground">
                                No tickets found.
                            </div>
                        ) : (
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-[80px]">ID</TableHead>
                                        <TableHead>Customer</TableHead>
                                        <TableHead>Issue</TableHead>
                                        <TableHead>Priority</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead>Date</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {tickets.map((ticket) => (
                                        <TableRow key={ticket.ticket_id}>
                                            <TableCell className="font-medium">#{ticket.ticket_id}</TableCell>
                                            <TableCell>
                                                <div className="flex flex-col">
                                                    <span className="font-medium">{ticket.customer_name}</span>
                                                    <span className="text-xs text-muted-foreground">
                                                        {ticket.phone_number || "No Phone"}
                                                    </span>
                                                </div>
                                            </TableCell>
                                            <TableCell className="max-w-[300px] truncate" title={ticket.issue_description}>
                                                {ticket.issue_description}
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={getPriorityColor(ticket.priority) as any}>
                                                    {ticket.priority}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                <Badge
                                                    variant={ticket.status === "Open" ? "outline" : "secondary"}
                                                    className={ticket.status === "Open" ? "border-green-500 text-green-600" : ""}
                                                >
                                                    {ticket.status}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                {format(new Date(ticket.created_at), "MMM d, h:mm a")}
                                            </TableCell>
                                            <TableCell className="text-right">
                                                {ticket.status !== "Closed" && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        onClick={() => handleCloseTicket(ticket.ticket_id)}
                                                        title="Mark as Resolved"
                                                    >
                                                        <CheckCircle className="h-4 w-4 text-green-600" />
                                                    </Button>
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        )}
                    </CardContent>
                </Card>
            </div>
        </DashboardLayout>
    );
}
