import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

import { setAccessToken } from "@/shared/api/client";
import { resetConnectivityForTests } from "@/shared/lib/connectivity";

// Экраны грузятся лениво (React.lazy): первый импорт модуля в тесте может занять больше секунды.
configure({ asyncUtilTimeout: 4000 });

afterEach(() => {
  cleanup();
  setAccessToken(null);
  resetConnectivityForTests();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
