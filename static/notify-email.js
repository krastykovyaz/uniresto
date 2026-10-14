// Which of a person's two addresses gets their notifications (order mails, courier mails).
// "private" is the default: their Communication email when they have one -- university inboxes
// sometimes block this app's automated mail -- else the University address, the only one they
// may have. "university" is the explicit choice to keep everything on the University address.
export const NOTIFY_CHOICES = ["private", "university"];

export function normalizeNotifyChoice(value) {
  return value === "university" ? "university" : "private";
}

export function pickNotifyEmail(choice, communicationEmail, registeredEmail) {
  if (normalizeNotifyChoice(choice) === "university" && registeredEmail) return registeredEmail;
  return communicationEmail || registeredEmail || "";
}

// The choice only means something with two different addresses.
export function hasTwoEmails(communicationEmail, registeredEmail) {
  return Boolean(
    communicationEmail && registeredEmail && communicationEmail.trim().toLowerCase() !== registeredEmail.trim().toLowerCase(),
  );
}
