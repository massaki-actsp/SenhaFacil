const clinicSlug = document.body.dataset.clinicSlug;
const clinicId = document.body.dataset.clinicId;
const calledTicket = document.querySelector("#calledTicket");
const calledRoom = document.querySelector("#calledRoom");
const waitingList = document.querySelector("#waitingList");

async function loadTickets() {
  const response = await fetch(`/api/senhas?clinic_slug=${clinicSlug}`);
  const data = await response.json();
  waitingList.innerHTML = data.tickets
    .filter((ticket) => ticket.status === "aguardando")
    .slice(0, 8)
    .map((ticket) => `<li><strong>${ticket.ticket_code}</strong><span>${ticket.category_label}</span></li>`)
    .join("");
}

const events = new EventSource(`/api/eventos/clinica/${clinicId}`);
events.addEventListener("queue_update", loadTickets);
events.addEventListener("queue_reset", () => {
  calledTicket.textContent = "---";
  calledRoom.textContent = "Aguardando chamada";
  loadTickets();
});
events.addEventListener("ticket_called", (event) => {
  const ticket = JSON.parse(event.data).ticket;
  calledTicket.textContent = ticket.ticket_code;
  calledRoom.textContent = ticket.room || "Recepcao";
  loadTickets();
});

loadTickets();
