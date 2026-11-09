/** Сообщения модуля 6 «Рабочее место механика»: подхватываются реестром shared/api/errors.ts автоматически. */

export const errorMessages: Record<string, string> = {
  another_task_active: "У вас уже есть работа в процессе",
  order_not_workable: "Заказ ещё не передан в работу",
};

export const fieldFallbacks: Record<string, string> = {
  item_id: "Работа недоступна",
  priority: "Выберите приоритет: низкий, средний или высокий",
  status: "Недопустимый статус",
};
