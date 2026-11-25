import { api } from "./api.js";
import { clear, h } from "./dom.js";

const modal = document.getElementById("modal");
const title = document.getElementById("modal-title");
const body = document.getElementById("modal-body");

document.getElementById("modal-close").addEventListener("click", closeModal);
modal.addEventListener("click", (event) => {
  if (event.target === modal) closeModal();
});

export function closeModal() {
  modal.hidden = true;
}

const EXAMPLE = `id: CASE-2611-0201
title: Short description of the case
seed:
  kind: complaint
  identifiers:
    - {type: phone, value: "+919800000000"}
    - {type: account, value: "IVBK0123456:50100012345678"}
evidence:
  - {file: evidence/complaint.txt, source: complaint}
  - {file: evidence/statement.csv, source: bank_statement, account: "IVBK0123456:50100012345678"}
  - {file: evidence/cdr.csv, source: cdr, colmap: {columns: {time: "Call Start"}, time_format: "%d/%m/%Y %H:%M"}}`;

export function openUpload(onDone) {
  title.textContent = "Add a case";
  clear(body);
  const input = h("input", { type: "file", accept: ".zip", "aria-label": "Case archive" });
  const status = h("div", { class: "faint" });
  const submit = h("button", { class: "btn", type: "button", text: "Upload and analyse" });
  submit.addEventListener("click", async () => {
    const file = input.files && input.files[0];
    if (!file) {
      status.textContent = "Choose a .zip file first.";
      return;
    }
    submit.disabled = true;
    status.textContent = "Uploading, hashing and analysing";
    try {
      const result = await api.upload(file);
      closeModal();
      onDone(result.id);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  body.append(
    h("p", {
      text: "Upload a .zip archive holding case.yaml and the evidence files it lists. Every file is hashed and logged in the custody ledger before analysis.",
    }),
    h("p", {
      class: "faint",
      text: "Supported source types: bank_statement, atm_journal, kyc_account, cdr, tower_list, tower_dump, kyc_subscriber, call_log, sms, chat, cloud_location, email, complaint, statement, net_conn, uniaethel, cctv_log, seizure_memo, media. A colmap entry maps differently named columns, time formats or time zones without code changes.",
    }),
    h("div", { class: "raw", text: EXAMPLE }),
    h("div", { class: "row", style: { marginTop: "12px" } }, input, submit),
    status,
  );
  modal.hidden = false;
}
