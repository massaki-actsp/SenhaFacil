const clinicSlug = document.body.dataset.clinicSlug;
const rows = document.querySelector("#reportRows");
const title = document.querySelector("#reportTitle");

async function loadReport(period) {
  const response = await fetch(`/api/relatorios/emissoes?clinic_slug=${clinicSlug}&period=${period}`);
  const data = await response.json();
  title.textContent = period === "daily" ? "Emissoes do dia" : "Emissoes da semana";
  rows.innerHTML = data.rows.length
    ? data.rows.map((row) => `
      <tr>
        <td>${row.day}</td>
        <td>${row.category}</td>
        <td><strong>${row.total}</strong></td>
      </tr>
    `).join("")
    : `<tr><td colspan="3">Nenhuma senha emitida no periodo.</td></tr>`;
}

document.querySelectorAll("[data-period]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-period]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    loadReport(button.dataset.period);
  });
});

loadReport("daily");
