// Isolated test double: no external dependencies, credentials, or persistent data.
import http from 'node:http';
import {randomUUID} from 'node:crypto';
const sessions = new Map(), orders = new Map();
let productCalls = 0;
let postSwitchFailure = false;
http.createServer(async (request, response) => {
  const path = new URL(request.url, 'http://internal').pathname;
  const reply = (status, body) => {response.writeHead(status, {'Content-Type': 'application/json'}); response.end(JSON.stringify(body));};
  if (path === '/version') return reply(200, {version: process.env.VERSION});
  if (path.startsWith('/health/')) return reply(path.endsWith('/ready') && process.env.READY === 'false' ? 503 : 200, {status: 'ok'});
  if (request.method !== 'GET' && request.headers.origin !== 'https://staging-boutique.narx.space') return reply(403, {});
  let id = /session=([a-f0-9-]+)/.exec(request.headers.cookie || '')?.[1];
  if (!id) {id = randomUUID(); response.setHeader('Set-Cookie', 'session=' + id + '; Path=/');}
  if (!sessions.has(id)) sessions.set(id, {items: [], keys: new Map()});
  const session = sessions.get(id);
  if (path === '/api/products') {
    productCalls++;
    if (process.env.FAIL_POST && request.headers['x-fixture-phase'] === 'serving') postSwitchFailure = true;
    if (postSwitchFailure) return reply(503, {});
    if (process.env.FAIL_AFTER && productCalls > Number(process.env.FAIL_AFTER)) return reply(503, {});
    return reply(200, [{id: 'mug', price: 1800}]);
  }
  if (path === '/api/cart') return reply(200, {items: session.items});
  if (path.startsWith('/api/cart/items/')) {
    if (path.endsWith('/missing')) return reply(404, {});
    if (request.method === 'DELETE') {session.items = []; return reply(200, {items: []});}
    let raw = ''; for await (const chunk of request) raw += chunk;
    const quantity = JSON.parse(raw).quantity;
    if (quantity > 20) return reply(400, {});
    session.items = [{productId: 'mug', quantity}];
    return reply(200, {items: session.items});
  }
  if (path === '/api/orders') {
    if (!session.items.length) return reply(409, {});
    const key = request.headers['idempotency-key'];
    if (!session.keys.has(key)) {
      const order = {id: randomUUID(), total: 1800 * session.items[0].quantity, currency: 'USD'};
      orders.set(order.id, {...order, owner: id}); session.keys.set(key, order);
    }
    return reply(200, session.keys.get(key));
  }
  if (path.startsWith('/api/orders/')) {
    const order = orders.get(path.split('/').at(-1));
    return order?.owner === id ? reply(200, {id: order.id, total: order.total, currency: order.currency}) : reply(404, {});
  }
  return reply(404, {});
}).listen(8080, '0.0.0.0');
