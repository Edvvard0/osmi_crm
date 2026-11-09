export interface TelegramStatus {
  enabled: boolean;
  bot_username: string | null;
  linked: boolean;
  telegram_username: string | null;
}

export interface LinkCode {
  code: string;
  link: string;
  expires_at: string;
}

export interface NotificationSetting {
  event_type: string;
  title: string;
  description: string;
  is_enabled: boolean;
  is_default: boolean;
}
