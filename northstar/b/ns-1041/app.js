// Northstar Checkout staging build. Fictional store, no backend, no real orders.
const BUILD = "ns-1041";
const PRODUCT = { sku: "NS-TB-750", name: "Trail Bottle", unitCents: 2400 };
const CART_KEY = `northstar:${BUILD}:cart`;
const view = document.getElementById("view");

// Test hook: ?reset=1 clears cart and route state, then opens the product page.
if (new URLSearchParams(location.search).get("reset") === "1") {
  Object.keys(localStorage).filter((k) => k.startsWith("northstar:")).forEach((k) => localStorage.removeItem(k));
  sessionStorage.clear();
  history.replaceState(null, "", location.pathname + "#/product");
}

const money = (cents) => `$${(cents / 100).toFixed(2)}`;
const loadCart = () => JSON.parse(localStorage.getItem(CART_KEY) || "[]");
const saveCart = (cart) => localStorage.setItem(CART_KEY, JSON.stringify(cart));
const cartCount = (cart) => cart.reduce((n, line) => n + line.qty, 0);
const cartSubtotal = (cart) => cart.reduce((sum, line) => sum + line.unitCents * line.qty, 0);
const reviewSubtotal = (cart) => cart.reduce((sum, line) => sum + line.unitCents, 0);

function addToCart() {
  const cart = loadCart();
  const line = cart.find((l) => l.sku === PRODUCT.sku);
  if (line) line.qty += 1;
  else cart.push({ ...PRODUCT, qty: 1 });
  saveCart(cart);
  location.hash = "#/cart";
}

function setQty(delta) {
  const cart = loadCart();
  const line = cart.find((l) => l.sku === PRODUCT.sku);
  if (!line) return;
  line.qty = Math.max(1, line.qty + delta);
  saveCart(cart);
  render();
}

const pages = {
  product: () => `
    <section class="card product">
      <div class="bottle" aria-hidden="true">
        <svg width="90" height="220" viewBox="0 0 90 220"><rect x="30" y="6" width="30" height="26" rx="6" fill="#0B3B5C"/>
        <rect x="14" y="30" width="62" height="184" rx="22" fill="#1F7A5C"/><rect x="24" y="80" width="42" height="70" rx="8" fill="#9FE3C8"/></svg>
      </div>
      <div>
        <p class="muted">SKU ${PRODUCT.sku}</p>
        <h1>${PRODUCT.name}</h1>
        <p class="muted">750 ml insulated steel bottle for day hikes.</p>
        <p class="price">${money(PRODUCT.unitCents)}</p>
        <button id="add">Add to cart</button>
      </div>
    </section>`,
  cart: (cart) => cart.length === 0
    ? `<section class="card"><h2>Your cart</h2><p>Your cart is empty.</p><a class="btn" href="#/product">Browse products</a></section>`
    : `<section class="card"><h2>Your cart</h2>
      <table><tr><th>Item</th><th>Unit price</th><th>Quantity</th><th class="num">Line total</th></tr>
      ${cart.map((l) => `<tr><td>${l.name}</td><td>${money(l.unitCents)}</td>
        <td><span class="qty"><button class="ghost" id="dec" aria-label="Decrease quantity">&minus;</button>
        <output aria-label="Quantity">${l.qty}</output>
        <button class="ghost" id="inc" aria-label="Increase quantity">+</button></span></td>
        <td class="num">${money(l.unitCents * l.qty)}</td></tr>`).join("")}
      </table>
      <div class="summary"><span>Cart subtotal</span><strong>${money(cartSubtotal(cart))}</strong></div>
      <div class="actions"><a class="btn" href="#/checkout">Proceed to checkout</a><a href="#/product">Continue shopping</a></div>
    </section>`,
  checkout: (cart) => cart.length === 0 ? pages.cart(cart) : `
    <section class="card"><h2>Checkout details</h2>
      <p class="muted">Staging uses a fixed fictional test customer. No account or payment details are collected.</p>
      <dl><dt>Name</dt><dd>Test Customer</dd><dt>Email</dt><dd>qa@northstar.test</dd>
      <dt>Address</dt><dd>100 Test Street, Springfield</dd><dt>Payment</dt><dd>None (staging)</dd></dl>
      <div class="actions"><a class="btn" href="#/review">Continue to review</a><a href="#/cart">Back to cart</a></div>
    </section>`,
  review: (cart) => cart.length === 0 ? pages.cart(cart) : `
    <section class="card"><h2>Review your order</h2>
      <table><tr><th>Item</th><th>Quantity</th><th class="num">Unit price</th></tr>
      ${cart.map((l) => `<tr><td>${l.name}</td><td>${l.qty}</td><td class="num">${money(l.unitCents)}</td></tr>`).join("")}
      </table>
      <div class="summary"><span>Order subtotal</span><strong>${money(reviewSubtotal(cart))}</strong></div>
      <p class="note">Purchases are disabled on this staging site. No order can be placed.</p>
      <div class="actions"><button disabled aria-disabled="true">Place order</button><a href="#/checkout">Back to details</a></div>
    </section>`,
};

function render() {
  const cart = loadCart();
  const route = (location.hash.replace("#/", "") || "product").split("?")[0];
  view.innerHTML = (pages[route] || pages.product)(cart);
  document.getElementById("cart-count").textContent = cartCount(cart);
  document.getElementById("add")?.addEventListener("click", addToCart);
  document.getElementById("inc")?.addEventListener("click", () => setQty(1));
  document.getElementById("dec")?.addEventListener("click", () => setQty(-1));
}

document.getElementById("build").textContent = BUILD;
window.addEventListener("hashchange", render);
render();
