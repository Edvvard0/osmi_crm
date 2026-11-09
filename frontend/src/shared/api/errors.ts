/** Клиент видит только безопасные сообщения из словаря — текст ошибки сервера в UI не попадает. */

const BASE_ERROR_MESSAGES: Record<string, string> = {
  bad_request: "Некорректный запрос",
  unauthorized: "Сессия истекла. Войдите снова",
  forbidden: "Нет доступа к этому разделу",
  not_found: "Не найдено",
  method_not_allowed: "Действие недоступно",
  conflict: "Данные уже изменились. Обновите страницу",
  unique_violation: "Такая запись уже существует",
  reference_violation: "Связанная запись не найдена или используется",
  constraint_violation: "Данные нарушают ограничения",
  payload_too_large: "Слишком большой запрос",
  unsupported_media_type: "Неподдерживаемый формат",
  validation_error: "Проверьте введённые данные",
  rate_limited: "Слишком много попыток. Повторите позже",
  internal_error: "Внутренняя ошибка сервера",
  network_error: "Нет соединения с сервером",
  offline: "Нет соединения — действие недоступно",
  service_unavailable: "Сервис временно недоступен. Попробуйте позже",
  timeout: "Сервер долго не отвечает. Попробуйте ещё раз",
  unknown: "Не удалось выполнить действие",
  invalid_credentials: "Неверный логин или пароль",
  account_locked: "Учётная запись временно заблокирована после неудачных попыток. Попробуйте через 15 минут",
  invalid_token: "Сессия недействительна. Войдите снова",
  invalid_current_password: "Неверный текущий пароль",
  duplicate_phone: "Клиент с таким телефоном уже есть в базе",
  duplicate_vin: "Автомобиль с таким VIN уже есть в базе",
  client_archived: "Клиент в архиве. Сначала восстановите его",
  vehicle_archived: "Автомобиль в архиве. Сначала восстановите его",
  duplicate_category_name: "Категория с таким названием в этом отделе уже есть",
  duplicate_service_code: "Услуга с таким кодом уже есть",
  duplicate_post_name: "Пост с таким названием на этой точке уже есть",
  duplicate_sku: "Позиция с таким артикулом уже есть",
  duplicate_barcode: "Позиция с таким штрихкодом уже есть",
  post_busy: "Пост занят",
  outside_working_hours: "Запись должна целиком укладываться в рабочие часы точки в пределах одних суток",
  invalid_transition: "Недопустимая смена статуса записи",
  invalid_state: "Запись в этом статусе изменить нельзя",
};

/** Подписи ошибок полей: сервер присылает код или свой текст — на экран идёт только то, что есть в словаре. */
const BASE_FIELD_MESSAGES: Record<string, string> = {
  required: "Обязательное поле",
  invalid: "Некорректное значение",
  weak_password: "Слишком простой пароль",
  password_too_short: "Пароль слишком короткий",
  unique_violation: "Такое значение уже используется",
  markup_not_allowed: "Нельзя использовать символы < и >",
};

const BASE_FIELD_FALLBACKS: Record<string, string> = {
  new_password: "Пароль слишком простой: не короче 10 символов, не должен совпадать с логином",
  current_password: "Проверьте текущий пароль",
  login: "Недопустимый логин",
  full_name: "Недопустимое ФИО",
  name: "Недопустимое название",
  address: "Недопустимый адрес",
  phone: "Недопустимый телефон",
  phone_extra: "Недопустимый телефон",
  email: "Недопустимый email",
  inn: "ИНН: 10 или 12 цифр",
  vin: "VIN: 17 символов, без букв I, O, Q",
  plate_number: "Недопустимый госномер",
  discount_percent: "Скидка: число от 0 до 100",
  company_name: "Недопустимое название компании",
  make: "Недопустимая марка",
  model: "Недопустимая модель",
  year: "Недопустимый год",
  mileage: "Недопустимый пробег",
  color: "Недопустимый цвет",
  notes: "Недопустимые заметки",
  code: "Недопустимый код",
  description: "Недопустимое описание",
  base_price: "Цена: число не меньше 0, до двух знаков после запятой",
  sale_price: "Цена: число не меньше 0, до двух знаков после запятой",
  price: "Цена: число не меньше 0, до двух знаков после запятой",
  norm_hours: "Нормочасы: число не меньше 0, до двух знаков после запятой",
  duration_minutes: "Длительность: целое число минут",
  sort_order: "Порядок: целое число",
  sku: "Недопустимый артикул",
  brand: "Недопустимый бренд",
  barcode: "Недопустимый штрихкод",
  timezone: "Недопустимый часовой пояс",
  work_start: "Недопустимое время начала работы",
  work_end: "Недопустимое время окончания работы",
  client_id: "Выберите клиента",
  vehicle_id: "Автомобиль не найден у этого клиента или находится в архиве",
  post_id: "Пост недоступен или относится к другому отделу",
  department: "Недопустимый отдел",
  service_ids: "Услуги неактивны или относятся к другому отделу",
  start_at: "Начало: время кратно 5 минутам",
  end_at: "Длительность: от 15 минут до 12 часов, кратно 5 минутам",
  comment: "Недопустимый комментарий",
  password: "Пароль слишком простой: не короче 10 символов, не должен совпадать с логином",
};

/**
 * Реестр сообщений модулей: каждый модуль кладёт свои тексты в features/<имя>/errors.ts
 * (экспорты errorMessages, fieldMessages, fieldFallbacks) — общий файл править не нужно.
 */
interface FeatureMessages {
  errorMessages?: Record<string, string>;
  fieldMessages?: Record<string, string>;
  fieldFallbacks?: Record<string, string>;
}
const featureMessages = Object.values(
  import.meta.glob<FeatureMessages>("../../features/*/errors.ts", { eager: true }),
);
const merge = (base: Record<string, string>, pick: (m: FeatureMessages) => Record<string, string> | undefined) =>
  Object.assign({}, base, ...featureMessages.map((m) => pick(m) ?? {})) as Record<string, string>;

export const ERROR_MESSAGES = merge(BASE_ERROR_MESSAGES, (m) => m.errorMessages);
export const FIELD_MESSAGES = merge(BASE_FIELD_MESSAGES, (m) => m.fieldMessages);
const FIELD_FALLBACKS = merge(BASE_FIELD_FALLBACKS, (m) => m.fieldFallbacks);

const STATUS_CODES: Record<number, string> = {
  400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
  405: "method_not_allowed", 409: "conflict", 413: "payload_too_large",
  415: "unsupported_media_type", 422: "validation_error", 429: "rate_limited",
};

export class AppError extends Error {
  readonly code: string;
  readonly status: number;
  readonly fields: Record<string, string>;
  readonly requestId?: string;
  readonly retryAfter?: number;
  /** Структурированные подсказки сервера (например, id существующей записи при дубле). Только строки. */
  readonly details: Record<string, string>;

  constructor(
    code: string,
    status = 0,
    fields: Record<string, string> = {},
    requestId?: string,
    retryAfter?: number,
    details: Record<string, string> = {},
  ) {
    super(code === "rate_limited" && retryAfter ? `Слишком много попыток. Повторите через ${retryAfter} с` : messageFor(code));
    this.name = "AppError";
    this.code = code;
    this.status = status;
    this.fields = fields;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
    this.details = details;
  }
}

export function messageFor(code: string): string {
  return ERROR_MESSAGES[code] ?? ERROR_MESSAGES.unknown;
}

export function codeForStatus(status: number): string {
  if (STATUS_CODES[status]) return STATUS_CODES[status];
  if (status === 502 || status === 503 || status === 504) return "service_unavailable";
  return status >= 500 ? "internal_error" : "unknown";
}

/** Любое исключение → AppError с безопасным сообщением. */
export function toAppError(e: unknown): AppError {
  if (e instanceof AppError) return e;
  return new AppError("unknown");
}

/** Ошибка поля с подсказкой формы: известный код (например, markup_not_allowed) важнее общей подсказки. */
export function fieldText(e: AppError | null | undefined, name: string, hint: string): string | undefined {
  const v = e?.fields[name];
  if (v === undefined) return undefined;
  return v === "required" || v === "invalid" ? hint : (FIELD_MESSAGES[v] ?? hint);
}

/** Текст ошибки под полем формы (серверный текст не используется). */
export function fieldMessage(e: AppError | null | undefined, name: string): string | undefined {
  const v = e?.fields[name];
  if (v === undefined) return undefined;
  return FIELD_MESSAGES[v] ?? FIELD_FALLBACKS[name] ?? FIELD_MESSAGES.invalid;
}
