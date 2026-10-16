// Expenses live in the page for this visit; keeping them between visits is a later milestone.
const expenses = [];
const $ = (id) => document.getElementById(id);

function parseAmount(text) {
  return Number(text.replace(",", ".")) || 0;
}

function render() {
  const show = $("show").value;
  const shown = expenses.filter((e) => show === "all" || e.category === show);
  $("list").replaceChildren(...shown.map((e) => {
    const li = document.createElement("li");
    li.textContent = `${e.category} ${e.amount.toFixed(2)}`;
    return li;
  }));
  $("empty").hidden = shown.length > 0;
  $("total").textContent = expenses.reduce((sum, e) => sum + e.amount, 0).toFixed(2);
}

$("add").addEventListener("submit", (event) => {
  event.preventDefault();
  const amount = parseAmount($("amount").value);
  $("message").textContent = "";
  expenses.push({ category: $("category").value, amount });
  $("amount").value = "";
  render();
});

$("show").addEventListener("change", render);
render();
