import { expect, test, type FrameLocator, type Page } from "@playwright/test";

const firstWord = process.env.GOLDENDICT_E2E_FIRST_WORD?.trim() || "example";
const secondWord = process.env.GOLDENDICT_E2E_SECOND_WORD?.trim() || "hello";
const apiUrl = process.env.GOLDENDICT_E2E_API_URL?.trim();
const dictionaryPattern = new RegExp(
  process.env.GOLDENDICT_E2E_DICTIONARY_PATTERN?.trim() || "OALDPE",
  "i",
);

interface OaldpeLookup {
  bridgeId: string;
  frame: FrameLocator;
  iframeHeight: number;
}

async function lookup(page: Page, word: string): Promise<OaldpeLookup> {
  await page.locator("#query").fill(word);
  await page.getByRole("button", { name: "Look up" }).click();
  const view = page.locator("#dictionary-view");
  await expect.poll(() => view.evaluate((node) => {
    const response = (node as HTMLElement & { response?: { word?: string } }).response;
    return response?.word;
  })).toBe(word);
  await expect(page.locator("#view-state")).toHaveAttribute("data-state", "ready");

  const iframe = view.locator("iframe");
  await expect(iframe).toBeVisible();
  const frame = iframe.contentFrame();
  await expect(frame.locator(".oald.visible").first()).toBeVisible();
  await expect(frame.locator(".oaldpe-config-gear__icon").first()).toBeVisible();
  await expect.poll(() => frame.locator("html").evaluate(() => {
    try {
      return (0, eval)("oaldpeInit.scriptExecutionCounter") as number;
    } catch {
      return 0;
    }
  })).toBeGreaterThan(0);
  await frame.locator("html").evaluate(async () => await document.fonts.ready);

  const srcdoc = (await iframe.getAttribute("srcdoc")) ?? "";
  const bridgeId = /"instanceId":"([^"]+)"/.exec(srcdoc)?.[1] ?? "";
  expect(bridgeId).not.toBe("");
  return {
    bridgeId,
    frame,
    iframeHeight: await iframe.evaluate((element) => element.getBoundingClientRect().height),
  };
}

test("real OALDPE sidecars retain GoldenDict geometry across lookups", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(`page error: ${error.message}`));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource:")
    ) {
      failures.push(`console: ${message.text()}`);
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/v1/")) {
      failures.push(
        `request: ${request.url()}: ${request.failure()?.errorText ?? "failed"}`,
      );
    }
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/") && response.status() >= 400) {
      failures.push(`response: ${response.url()}: HTTP ${response.status()}`);
    }
  });

  await page.goto("/");
  if (apiUrl) {
    await page.locator("#api-base").fill(apiUrl);
    await page.locator("#api-base").dispatchEvent("change");
  }
  await expect(page.locator("#connection-text")).toContainText("ready");
  const options = page.locator(".dictionary-option");
  await expect(options.first()).toBeVisible();
  const count = await options.count();
  let selected = false;
  for (let index = 0; index < count; index += 1) {
    const option = options.nth(index);
    const checkbox = option.locator('input[type="checkbox"]');
    const matches = dictionaryPattern.test((await option.textContent()) ?? "");
    await checkbox.setChecked(matches);
    selected ||= matches;
  }
  expect(selected, `No loaded dictionary matched ${dictionaryPattern}`).toBe(true);
  await expect(page.locator("#script-policy")).toHaveValue("sandboxed");
  await expect(page.locator("#layout-mode")).toHaveValue("fidelity");

  const first = await lookup(page, firstWord);
  await expect(first.frame.locator("html")).toHaveAttribute("data-gd-layout", "fidelity");
  await expect(first.frame.locator('style[data-gd-style="responsive"]')).toHaveCount(0);
  const firstResult = await first.frame.locator("html").evaluate(() => {
    const gear = document.querySelector<HTMLElement>(".oaldpe-config-gear__icon");
    const webtop = document.querySelector<HTMLElement>(
      ".entry > .top-container .webtop",
    );
    const oald = document.querySelector<HTMLElement>(".oald.visible");
    const headword = document.querySelector<HTMLElement>(".headword");
    if (!gear || !webtop || !oald || !headword) {
      throw new Error("OALDPE did not create its expected article controls");
    }
    const gearRect = gear.getBoundingClientRect();
    const webtopRect = webtop.getBoundingClientRect();
    const topContainerRect = webtop.closest(".top-container")?.getBoundingClientRect();
    const dictionaryHeaderRect = document
      .querySelector("gd-dict-header")
      ?.getBoundingClientRect();
    const definition = document.querySelector<HTMLElement>(".def");
    const example = document.querySelector<HTMLElement>(".x");
    const definitionStyle = definition ? getComputedStyle(definition) : undefined;
    const exampleStyle = example ? getComputedStyle(example) : undefined;
    const chinese = [...document.querySelectorAll<HTMLElement>("chn")];
    const runtime = globalThis as typeof globalThis & {
      __DICT__?: { name?: string; version?: string };
      jQuery?: { fn?: { jquery?: string } };
    };
    return {
      chineseTotal: chinese.length,
      chineseVisible: chinese.filter((node) => node.getClientRects().length > 0).length,
      dictionaryRuntime: runtime.__DICT__,
      documentClientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      dictionaryHeaderHeight: dictionaryHeaderRect?.height,
      definitionStyle: definitionStyle
        ? {
            fontFamily: definitionStyle.fontFamily,
            fontSize: definitionStyle.fontSize,
            lineHeight: definitionStyle.lineHeight,
          }
        : undefined,
      exampleStyle: exampleStyle
        ? {
            fontFamily: exampleStyle.fontFamily,
            fontSize: exampleStyle.fontSize,
            fontStyle: exampleStyle.fontStyle,
            lineHeight: exampleStyle.lineHeight,
          }
        : undefined,
      fontsStatus: document.fonts.status,
      gear: {
        bottom: gearRect.bottom,
        height: gearRect.height,
        left: gearRect.left,
        right: gearRect.right,
        top: gearRect.top,
        width: gearRect.width,
      },
      headword: headword.textContent?.trim() ?? "",
      jqueryVersion: runtime.jQuery?.fn?.jquery,
      oaldDisplay: getComputedStyle(oald).display,
      stylesheetHrefs: [...document.styleSheets]
        .map((sheet) => sheet.href)
        .filter((href): href is string => Boolean(href)),
      topContainerHeight: topContainerRect?.height,
      visibleEntries: document.querySelectorAll(".oald.visible").length,
      webtop: {
        bottom: webtopRect.bottom,
        left: webtopRect.left,
        right: webtopRect.right,
        top: webtopRect.top,
      },
    };
  });
  expect(firstResult.dictionaryRuntime?.name).toBe("GoldenDict");
  expect(firstResult.jqueryVersion).toBe("3.7.1");
  expect(firstResult.fontsStatus).toBe("loaded");
  expect(firstResult.headword.toLocaleLowerCase()).toContain(firstWord.toLocaleLowerCase());
  expect(firstResult.oaldDisplay).not.toBe("none");
  expect(firstResult.visibleEntries).toBeGreaterThan(0);
  expect(firstResult.chineseTotal).toBeGreaterThan(0);
  expect(firstResult.chineseVisible).toBe(0);
  expect(firstResult.stylesheetHrefs.at(-1)).toMatch(/\/oaldpe\.css(?:\?|$)/i);
  expect(firstResult.definitionStyle).toMatchObject({
    fontSize: "15px",
    lineHeight: "21px",
  });
  expect(firstResult.definitionStyle?.fontFamily).toMatch(/Bookerly/i);
  expect(firstResult.exampleStyle).toMatchObject({
    fontSize: "15px",
    fontStyle: "italic",
    lineHeight: "21px",
  });
  expect(firstResult.exampleStyle?.fontFamily).toMatch(/Bookerly/i);
  expect(firstResult.dictionaryHeaderHeight).toBeCloseTo(23.65625, 1);
  if (firstWord.toLocaleLowerCase() === "example") {
    expect(firstResult.topContainerHeight).toBeCloseTo(124, 1);
    expect(firstResult.webtop.bottom - firstResult.webtop.top).toBeCloseTo(100.5, 1);
  }
  expect(firstResult.gear.width).toBeCloseTo(30, 0);
  expect(firstResult.gear.height).toBeCloseTo(30, 0);
  expect(firstResult.gear.left).toBeGreaterThan(firstResult.webtop.left);
  expect(firstResult.gear.right).toBeLessThan(firstResult.webtop.right);
  expect(firstResult.gear.top).toBeGreaterThan(firstResult.webtop.top);
  expect(firstResult.gear.bottom).toBeLessThan(firstResult.webtop.bottom);
  expect(firstResult.documentScrollWidth).toBeLessThanOrEqual(
    firstResult.documentClientWidth,
  );
  expect(first.iframeHeight).toBeGreaterThan(500);

  const second = await lookup(page, secondWord);
  expect(second.bridgeId).not.toBe(first.bridgeId);
  const secondResult = await second.frame.locator("html").evaluate(() => ({
    dictionaryName: (globalThis as typeof globalThis & {
      __DICT__?: { name?: string };
    }).__DICT__?.name,
    headword: document.querySelector(".headword")?.textContent?.trim() ?? "",
    gearCount: document.querySelectorAll(".oaldpe-config-gear__icon").length,
    visibleEntries: document.querySelectorAll(".oald.visible").length,
  }));
  expect(secondResult.dictionaryName).toBe("GoldenDict");
  expect(secondResult.headword.toLocaleLowerCase()).toContain(
    secondWord.toLocaleLowerCase(),
  );
  expect(secondResult.gearCount).toBeGreaterThan(0);
  expect(secondResult.visibleEntries).toBeGreaterThan(0);
  expect(second.iframeHeight).toBeGreaterThan(500);
  expect(failures).toEqual([]);
});
