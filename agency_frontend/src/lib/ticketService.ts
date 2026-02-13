
import { Ticket } from "./types";

const API_Base = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const ticketService = {
    // Get all tickets
    getAllTickets: async (): Promise<Ticket[]> => {
        try {
            const response = await fetch(`${API_Base}/tickets/`);
            if (!response.ok) throw new Error("Failed to fetch tickets");
            return await response.json();
        } catch (error) {
            console.error("Error fetching tickets:", error);
            return [];
        }
    },

    // Close a ticket
    closeTicket: async (ticketId: number): Promise<boolean> => {
        try {
            const response = await fetch(`${API_Base}/tickets/${ticketId}/close`, {
                method: "PATCH",
            });
            return response.ok;
        } catch (error) {
            console.error(`Error closing ticket ${ticketId}:`, error);
            return false;
        }
    },
};
