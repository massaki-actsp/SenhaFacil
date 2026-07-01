const clinicSlug = document.body.dataset.clinicSlug;
const clinicId = document.body.dataset.clinicId;
const rows = document.querySelector("#ticketRows");
const roomInput = document.querySelector("#roomInput");
const nextButton = document.querySelector("#nextButton");

async function loadTickets() {
  const response = await fetch(`/api/senhas?clinic_slug=${clinicSlug}`);
  const data = await response.json();
  rows.innerHTML = data.tickets.map((ticket) => `
    <tr>
      <td><strong>${ticket.ticket_code}</strong></td>
      <td>${ticket.category_label}</td>
      <td><span class="badge">${ticket.status}</span></td>
      <td>${ticket.position}</td>
      <td>${ticket.room || "-"}</td>
      <td>${ticket.status === "chamado" ? `<button class="segmented" data-complete="${ticket.id}">Finalizar</button>` : ""}</td>
    </tr>
  `).join("");
}

async function callNext() {
  const response = await fetch("/api/senhas/proxima", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clinic_slug: clinicSlug, room: roomInput.value }),
  });
  const data = await response.json();
  if (!data.ticket) alert(data.message || "Fila vazia.");
  loadTickets();
}

async function completeTicket(ticketId) {
  await fetch(`/api/senhas/${ticketId}/finalizar`, { method: "POST" });
  loadTickets();
}

nextButton.addEventListener("click", callNext);
rows.addEventListener("click", (event) => {
  const button = event.target.closest("[data-complete]");
  if (button) completeTicket(button.dataset.complete);
});

const events = new EventSource(`/api/eventos/clinica/${clinicId}`);
events.addEventListener("queue_update", loadTickets);
events.addEventListener("ticket_called", loadTickets);
events.addEventListener("queue_reset", loadTickets);

loadTickets();
