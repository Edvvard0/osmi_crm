/** Сообщения модуля 7 «Telegram»: подхватываются реестром shared/api/errors.ts автоматически. */

export const errorMessages: Record<string, string> = {
  telegram_disabled: "Telegram не настроен, обратитесь к руководителю",
  already_linked: "Аккаунт уже привязан к Telegram",
  telegram_unavailable: "Telegram недоступен или не принял сообщение. Проверьте ID чата и попробуйте позже",
};

export const fieldFallbacks: Record<string, string> = {
  telegram_chat_id: "Укажите ID чата точки (целое число)",
  items: "Недопустимый список уведомлений",
};
