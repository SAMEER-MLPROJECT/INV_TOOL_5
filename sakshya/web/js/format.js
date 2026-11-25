const istFull = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const istShort = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const inrFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function ist(epoch, short = false) {
  if (epoch === null || epoch === undefined) return "";
  return (short ? istShort : istFull).format(new Date(epoch * 1000)).replace(",", "");
}

export function inr(value) {
  if (value === null || value === undefined) return "";
  return `Rs ${inrFormat.format(Math.round(value))}`;
}

export function signed(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function pct(value, digits = 0) {
  if (value === null || value === undefined) return "";
  return `${(value * 100).toFixed(digits)}%`;
}

export function lr(w) {
  const value = Math.pow(10, w);
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} million`;
  if (value >= 1000) return inrFormat.format(Math.round(value));
  if (value >= 10) return value.toFixed(0);
  return value.toFixed(2);
}

export function duration(seconds) {
  const total = Math.round(Math.abs(seconds));
  const sign = seconds < 0 ? "-" : "+";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${sign}${hours} h ${String(minutes).padStart(2, "0")} min`;
  if (minutes) return `${sign}${minutes} min ${String(secs).padStart(2, "0")} s`;
  return `${sign}${secs} s`;
}

export function words(text) {
  return String(text || "").replace(/_/g, " ");
}

export function short(entity) {
  if (!entity) return "";
  const idx = entity.indexOf(":");
  const kind = entity.slice(0, idx);
  const value = entity.slice(idx + 1);
  if (kind === "account" && value.includes(":")) return value.replace(":", " ");
  return value;
}

export function kindOf(entity) {
  return entity ? entity.slice(0, entity.indexOf(":")) : "";
}

export const KIND_LABELS = {
  phone: "Phone",
  imei: "Handset",
  imsi: "SIM",
  account: "Account",
  account_masked: "Masked account",
  upi: "UPI ID",
  email: "Email",
  ip: "IP",
  mac: "Device",
  host: "Hostname",
  cloud: "Cloud account",
  atm: "ATM",
  cell: "Cell",
  domain: "Domain",
  sender: "Sender",
  person: "Person",
};

export const LINK_TYPES = {
  same_event: "Same event",
  co_presence: "Present at event",
  same_actor: "Same person",
  sequence: "Sequence",
  impossibility: "Could not be there",
};

export const STATUS_TONE = {
  inferred: "teal",
  confirmed: "good",
  rejected: "bad",
  candidate: "warn",
  weak: "grey",
  observed: "grey",
};
