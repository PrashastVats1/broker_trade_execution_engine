import type { OrderView } from "../types";
import { orderStatusNote } from "../statusText";
import { StatusBadge } from "./StatusBadge";

export function OrderResults({ orders }: { orders: OrderView[] }) {
  return (
    <section>
      <h2>Orders</h2>
      {orders.length === 0 ? <p>No orders yet.</p> : null}
      {orders.map((order, index) => {
        const note = orderStatusNote(order.status, order.error_message);
        return (
          <article className="order" key={order.id}>
            <p>
              {index + 1}. {order.symbol} {order.side} {order.quantity}
            </p>
            <p>
              Status: <StatusBadge status={order.status} />
            </p>
            <p>Filled quantity: {order.filled_quantity}</p>
            {order.broker_order_id ? <p>Broker order ID: {order.broker_order_id}</p> : null}
            {note ? <p>{note}</p> : null}
          </article>
        );
      })}
    </section>
  );
}
