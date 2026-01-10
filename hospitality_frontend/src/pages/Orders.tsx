import { useState } from "react";
import { ShoppingCart, Clock, CheckCircle2, User, Phone, FileText } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrders, useTodayCompletedCount, useUpdateOrder } from "@/hooks/use-orders";
import { toast } from "@/hooks/use-toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const statusColors = {
  pending: "bg-yellow-500/10 text-yellow-600 border-yellow-500/20",
  preparing: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  ready: "bg-purple-500/10 text-purple-600 border-purple-500/20",
  completed: "bg-green-500/10 text-green-600 border-green-500/20",
  cancelled: "bg-red-500/10 text-red-600 border-red-500/20",
};

export default function Orders() {
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const { data: allOrdersData, isLoading: isLoadingOrders } = useOrders(1, 100); // Get all orders
  const { data: todayCompletedData, isLoading: isLoadingCompleted } = useTodayCompletedCount();
  const updateOrderMutation = useUpdateOrder();
  
  // Filter pending orders for stats
  const pendingOrders = allOrdersData?.items.filter(order => order.status === "pending") || [];

  const selectedOrder = allOrdersData?.items.find(
    (order) => order.order_id === selectedOrderId
  );

  const handleStatusUpdate = async (orderId: string, newStatus: string) => {
    try {
      await updateOrderMutation.mutateAsync({
        orderId,
        updates: { status: newStatus as any },
      });
      toast({
        title: "Order Updated",
        description: `Order status changed to ${newStatus}`,
      });
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to update order status",
        variant: "destructive",
      });
    }
  };

  const stats = [
    {
      label: "Pending Orders",
      value: pendingOrders.length.toString(),
      icon: Clock,
      color: "text-yellow-600",
    },
    {
      label: "Completed Today",
      value: todayCompletedData?.count.toString() ?? "0",
      icon: CheckCircle2,
      color: "text-green-600",
    },
    {
      label: "Total Orders",
      value: allOrdersData?.total.toString() ?? "0",
      icon: ShoppingCart,
      color: "text-blue-600",
    },
  ];

  return (
    <DashboardLayout>
      <div className="max-w-7xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">Orders</h1>
          <p className="text-muted-foreground mt-2">
            Manage incoming orders from customers
          </p>
        </header>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {stats.map((stat) => (
            <Card key={stat.label}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {stat.label}
                </CardTitle>
                <stat.icon className={`h-4 w-4 ${stat.color}`} />
              </CardHeader>
              <CardContent>
                {isLoadingOrders || isLoadingCompleted ? (
                  <Skeleton className="h-8 w-20" />
                ) : (
                  <div className="text-2xl font-bold">{stat.value}</div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* All Orders */}
        <Card>
          <CardHeader>
            <CardTitle>All Orders</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoadingOrders ? (
              <div className="space-y-4">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-32 w-full" />
                ))}
              </div>
            ) : allOrdersData?.items.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <ShoppingCart className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>No orders</p>
              </div>
            ) : (
              <div className="space-y-4">
                {allOrdersData?.items.map((order) => (
                  <Card
                    key={order.order_id}
                    className="cursor-pointer hover:shadow-md transition-shadow"
                    onClick={() => setSelectedOrderId(order.order_id)}
                  >
                    <CardContent className="p-6">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-3 mb-3">
                            <Badge className={statusColors[order.status]}>
                              {order.status}
                            </Badge>
                            <span className="text-sm font-mono text-muted-foreground">
                              {order.order_id}
                            </span>
                            <span className="text-sm text-muted-foreground">
                              {formatDate(order.order_timestamp)} at {formatTime(order.order_timestamp)}
                            </span>
                          </div>
                          
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <User className="h-4 w-4 text-muted-foreground" />
                              <span className="font-medium">{order.caller_name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <Phone className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm text-muted-foreground">{order.caller_phone}</span>
                            </div>
                          </div>

                          <div className="mt-4">
                            <h4 className="text-sm font-medium mb-2">Items:</h4>
                            <ul className="space-y-1">
                              {order.items.map((item, idx) => (
                                <li key={idx} className="text-sm text-muted-foreground">
                                  • {item.name} x{item.quantity}
                                  {item.price && ` - ₹${item.price * item.quantity}`}
                                </li>
                              ))}
                            </ul>
                          </div>

                          {order.estimated_time_minutes && (
                            <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                              <Clock className="h-4 w-4" />
                              Estimated time: {order.estimated_time_minutes} minutes
                            </div>
                          )}
                        </div>

                        <div className="flex flex-col gap-2 ml-4">
                          <Select
                            value={order.status}
                            onValueChange={(value) => handleStatusUpdate(order.order_id, value)}
                          >
                            <SelectTrigger className="w-32">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="pending">Pending</SelectItem>
                              <SelectItem value="preparing">Preparing</SelectItem>
                              <SelectItem value="ready">Ready</SelectItem>
                              <SelectItem value="completed">Completed</SelectItem>
                              <SelectItem value="cancelled">Cancelled</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Order Detail Dialog */}
        {selectedOrder && (
          <Dialog open={!!selectedOrderId} onOpenChange={() => setSelectedOrderId(null)}>
            <DialogContent className="max-w-2xl max-h-[80vh]">
              <DialogHeader>
                <DialogTitle>Order Details - {selectedOrder.order_id}</DialogTitle>
                <DialogDescription>
                  Order placed on {formatDate(selectedOrder.order_timestamp)} at {formatTime(selectedOrder.order_timestamp)}
                </DialogDescription>
              </DialogHeader>
              <ScrollArea className="max-h-[60vh] pr-4">
                <div className="space-y-6">
                  <div>
                    <h3 className="font-medium mb-2">Customer Information</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center gap-2">
                        <User className="h-4 w-4 text-muted-foreground" />
                        <span>{selectedOrder.caller_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Phone className="h-4 w-4 text-muted-foreground" />
                        <span>{selectedOrder.caller_phone}</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="font-medium mb-2">Order Items</h3>
                    <div className="space-y-2">
                      {selectedOrder.items.map((item, idx) => (
                        <div key={idx} className="flex justify-between items-center p-3 bg-muted rounded-lg">
                          <div>
                            <div className="font-medium">{item.name}</div>
                            {item.notes && (
                              <div className="text-sm text-muted-foreground">{item.notes}</div>
                            )}
                          </div>
                          <div className="text-right">
                            <div>Qty: {item.quantity}</div>
                            {item.price && (
                              <div className="text-sm font-medium">₹{item.price * item.quantity}</div>
                            )}
                          </div>
                        </div>
                      ))}
                      {selectedOrder.total_amount && (
                        <div className="flex justify-between items-center pt-2 border-t">
                          <span className="font-medium">Total</span>
                          <span className="font-bold text-lg">₹{selectedOrder.total_amount}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {selectedOrder.notes && (
                    <div>
                      <h3 className="font-medium mb-2 flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        Notes
                      </h3>
                      <p className="text-sm text-muted-foreground">{selectedOrder.notes}</p>
                    </div>
                  )}

                  {selectedOrder.estimated_time_minutes && (
                    <div>
                      <h3 className="font-medium mb-2 flex items-center gap-2">
                        <Clock className="h-4 w-4" />
                        Estimated Time
                      </h3>
                      <p className="text-sm">{selectedOrder.estimated_time_minutes} minutes</p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </DashboardLayout>
  );
}

