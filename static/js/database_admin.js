const clinicSlug = document.body.dataset.clinicSlug;
const clinicId = document.body.dataset.clinicId;
const rows = document.querySelector("#adminTicketRows");
const todayCounter = document.querySelector("#todayCounter");
const resetTodayButton = document.querySelector("#resetTodayButton");
const deleteAllButton = document.querySelector("#deleteAllButton");
let currentPeriod = "today";

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("pt-BR");
}

async function loadAdminTickets() {
  const response = await fetch(`/api/admin/senhas?clinic_slug=${clinicSlug}&period=${currentPeriod}`);
  const data = await response.json();
  todayCounter.textContent = `${data.today_counter} senha(s) emitida(s) hoje`;
  rows.innerHTML = data.tickets.length
    ? data.tickets.map((ticket) => `
      <tr>
        <td><strong>${ticket.ticket_code}</strong></td>
        <td>${ticket.category_label}</td>
        <td><span class="badge">${ticket.status}</span></td>
        <td>${formatDate(ticket.issued_at)}</td>
        <td>${formatDate(ticket.called_at)}</td>
        <td>${ticket.room || "-"}</td>
        <td><button class="danger-button small" data-delete-ticket="${ticket.id}">Apagar</button></td>
      </tr>
    `).join("")
    : `<tr><td colspan="7">Nenhum registro encontrado.</td></tr>`;
}

async function deleteTicket(ticketId) {
  if (!confirm("Deseja apagar esta senha da base de dados?")) return;
  await fetch(`/api/admin/senhas/${ticketId}`, { method: "DELETE" });
  loadAdminTickets();
}

async function resetTodayQueue() {
  const message = "Deseja resetar a fila de hoje? Todas as senhas de hoje serao apagadas e a numeracao volta para 001.";
  if (!confirm(message)) return;
  await fetch("/api/admin/fila/resetar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clinic_slug: clinicSlug }),
  });
  loadAdminTickets();
}

async function deleteAllRecords() {
  const message = "Deseja apagar TODOS os registros desta unidade? Esta acao remove historico e contadores.";
  if (!confirm(message)) return;
  await fetch(`/api/admin/registros?clinic_slug=${clinicSlug}`, { method: "DELETE" });
  loadAdminTickets();
}

document.querySelectorAll("[data-period]").forEach((button) => {
  button.addEventListener("click", () => {
    currentPeriod = button.dataset.period;
    document.querySelectorAll("[data-period]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    loadAdminTickets();
  });
});

rows.addEventListener("click", (event) => {
  const button = event.target.closest("[data-delete-ticket]");
  if (button) deleteTicket(button.dataset.deleteTicket);
});

resetTodayButton.addEventListener("click", resetTodayQueue);
deleteAllButton.addEventListener("click", deleteAllRecords);

const events = new EventSource(`/api/eventos/clinica/${clinicId}`);
events.addEventListener("queue_update", loadAdminTickets);
events.addEventListener("queue_reset", loadAdminTickets);
events.addEventListener("ticket_called", loadAdminTickets);

loadAdminTickets();
