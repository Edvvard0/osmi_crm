import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setAccessToken } from "@/shared/api/client";

afterEach(() => {
  cleanup();
  setAccessToken(null);
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
